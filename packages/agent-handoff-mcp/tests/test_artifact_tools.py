"""Integration tests for artifact MCP tools (core.py wrappers).

These tests exercise the full tool call path against temporary sidecar DBs,
verifying JSON response shapes, task-ref resolution, and error handling.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.config import RuntimeConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Provision an isolated handoff + artifact DB environment."""
    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(
        tmp_path,
        state_dir=state_dir,
    )
    mcp_server.configure_runtime(runtime)

    # Seed a minimal active handoff task so task_ref resolution works
    handoff_core.set_handoff_state(
        task_ref="test-task",
        objective="Test task for artifact tools",
        status="in_progress",
    )

    return {
        "state_dir": state_dir,
        "artifact_db_path": runtime.artifact_db_path,
        "task_ref": "test-task",
    }


def _parse(payload: str | dict) -> dict:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


_LARGE_CONTENT = "log line output text\n" * 200


# ---------------------------------------------------------------------------
# record_artifact
# ---------------------------------------------------------------------------


def test_record_artifact_returns_ok(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            source_kind="log",
            source_label="pytest-output",
            content=_LARGE_CONTENT,
            content_type="text/plain",
            summary="Test run logs",
        )
    )
    assert result["ok"] is True
    assert result["was_updated"] is True
    assert result["source_id"] is not None
    assert result["chunk_count"] > 0


def test_record_artifact_resolves_active_task(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref=None,  # should resolve to active task
            source_kind="doc",
            source_label="active-doc",
            content=_LARGE_CONTENT,
        )
    )
    assert result["ok"] is True


def test_record_artifact_requires_source_kind(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            source_kind="",
            source_label="label",
            content=_LARGE_CONTENT,
        )
    )
    assert result["ok"] is False
    assert "source_kind" in result["error"]


def test_record_artifact_requires_source_label(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            source_kind="log",
            source_label="",
            content=_LARGE_CONTENT,
        )
    )
    assert result["ok"] is False
    assert "source_label" in result["error"]


def test_record_artifact_requires_content(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            source_kind="log",
            source_label="empty",
            content="",
        )
    )
    assert result["ok"] is False
    assert "content" in result["error"]


def test_record_artifact_dedupes_on_reindex(isolated_env: dict) -> None:
    kwargs = dict(
        task_ref="test-task",
        source_kind="doc",
        source_label="readme",
        content=_LARGE_CONTENT,
    )
    first = _parse(handoff_core.record_artifact(**kwargs))
    second = _parse(handoff_core.record_artifact(**kwargs))
    assert first["ok"] is True
    assert second["ok"] is True
    assert second["was_updated"] is False
    assert first["source_id"] == second["source_id"]


def test_record_artifact_with_lane_and_app_root(isolated_env: dict) -> None:
    result = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            lane_id="backend",
            app_root="apps/svc",
            source_kind="test-output",
            source_label="backend-tests",
            content=_LARGE_CONTENT,
            summary="Backend pytest output",
        )
    )
    assert result["ok"] is True


# ---------------------------------------------------------------------------
# search_artifacts
# ---------------------------------------------------------------------------


def _seed_tool_artifacts(task_ref: str = "test-task") -> None:
    """Seed a variety of artifacts for search tests via the core tool."""
    handoff_core.record_artifact(
        task_ref=task_ref,
        lane_id="backend",
        source_kind="test-output",
        source_label="pytest-backend",
        content="FAILED test_migration_rollback\nAssertionError: column missing\n" * 50,
        content_type="text/plain",
    )
    handoff_core.record_artifact(
        task_ref=task_ref,
        lane_id="frontend",
        source_kind="test-output",
        source_label="vitest-frontend",
        content="PASS src/Widget.test.tsx\nFAIL src/useSync.test.tsx\n" * 50,
        content_type="text/plain",
    )


def test_search_artifacts_returns_hits(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(handoff_core.search_artifacts(queries=["migration rollback"]))
    assert result["ok"] is True
    assert result["total"] > 0
    assert len(result["hits"]) > 0


def test_search_artifacts_hit_has_expected_fields(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(handoff_core.search_artifacts(queries=["column missing"]))
    assert result["ok"] is True
    for hit in result["hits"]:
        assert "source_id" in hit
        assert "source_label" in hit
        assert "title" in hit
        assert "snippet" in hit
        assert "rank" in hit


def test_search_artifacts_scoped_by_lane(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(
        handoff_core.search_artifacts(
            queries=["FAIL"],
            task_ref="test-task",
            lane_id="frontend",
        )
    )
    assert result["ok"] is True
    for hit in result["hits"]:
        assert hit["lane_id"] == "frontend"


def test_search_artifacts_empty_queries_error(isolated_env: dict) -> None:
    result = _parse(handoff_core.search_artifacts(queries=[]))
    assert result["ok"] is False


def test_search_artifacts_no_match_returns_empty_hits(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(
        handoff_core.search_artifacts(queries=["xyzzy_nonexistent_9999"])
    )
    assert result["ok"] is True
    assert result["total"] == 0
    assert result["hits"] == []


def test_search_artifacts_respects_limit(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(handoff_core.search_artifacts(queries=["test"], limit=1))
    assert result["ok"] is True
    assert len(result["hits"]) <= 1


# ---------------------------------------------------------------------------
# get_artifact_source
# ---------------------------------------------------------------------------


def test_get_artifact_source_found(isolated_env: dict) -> None:
    record = _parse(
        handoff_core.record_artifact(
            task_ref="test-task",
            source_kind="doc",
            source_label="get-test-doc",
            content=_LARGE_CONTENT,
        )
    )
    result = _parse(
        handoff_core.get_artifact_source(source_id=record["source_id"])
    )
    assert result["ok"] is True
    assert result["source"]["source_label"] == "get-test-doc"
    assert "chunk_count" in result["source"]
    assert "chunks" in result["source"]
    assert isinstance(result["source"]["chunks"], list)
    assert len(result["source"]["chunks"]) == result["source"]["chunk_count"]
    if result["source"]["chunks"]:
        first = result["source"]["chunks"][0]
        assert first["chunk_order"] == 1
        assert "title" in first
        assert "body" in first


def test_get_artifact_source_not_found(isolated_env: dict) -> None:
    result = _parse(handoff_core.get_artifact_source(source_id=99999))
    assert result["ok"] is False
    assert "not found" in result["error"].lower()


def test_get_artifact_source_by_task_and_label(isolated_env: dict) -> None:
    handoff_core.record_artifact(
        task_ref="test-task",
        source_kind="doc",
        source_label="by-label-doc",
        content=_LARGE_CONTENT,
    )
    result = _parse(
        handoff_core.get_artifact_source(
            task_ref="test-task",
            source_label="by-label-doc",
        )
    )
    assert result["ok"] is True
    assert result["source"]["source_label"] == "by-label-doc"


def test_get_artifact_source_no_args_error(isolated_env: dict) -> None:
    result = _parse(handoff_core.get_artifact_source())
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# list_artifact_sources
# ---------------------------------------------------------------------------


def test_list_artifact_sources_returns_sources(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(handoff_core.list_artifact_sources(task_ref="test-task"))
    assert result["ok"] is True
    assert result["total"] >= 2
    for s in result["sources"]:
        assert s["task_ref"] == "test-task"


def test_list_artifact_sources_empty_db(isolated_env: dict) -> None:
    result = _parse(handoff_core.list_artifact_sources(task_ref="nonexistent"))
    assert result["ok"] is True
    assert result["total"] == 0
    assert result["sources"] == []


def test_list_artifact_sources_filters_by_lane(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(
        handoff_core.list_artifact_sources(
            task_ref="test-task",
            lane_id="backend",
        )
    )
    assert result["ok"] is True
    for s in result["sources"]:
        assert s["lane_id"] == "backend"


# ---------------------------------------------------------------------------
# purge_artifacts
# ---------------------------------------------------------------------------


def test_purge_artifacts_by_task_ref(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    result = _parse(handoff_core.purge_artifacts(task_ref="test-task"))
    assert result["ok"] is True
    assert result["purged_sources"] == 2

    after = _parse(handoff_core.list_artifact_sources(task_ref="test-task"))
    assert after["total"] == 0


def test_purge_artifacts_no_conditions_error(isolated_env: dict) -> None:
    result = _parse(handoff_core.purge_artifacts())
    assert result["ok"] is False
    assert "Provide" in result["error"]


def test_purge_artifacts_search_returns_empty_after_purge(isolated_env: dict) -> None:
    _seed_tool_artifacts()
    handoff_core.purge_artifacts(task_ref="test-task")
    hits = _parse(
        handoff_core.search_artifacts(
            queries=["migration"],
            task_ref="test-task",
        )
    )
    assert hits["ok"] is True
    assert hits["total"] == 0


# ---------------------------------------------------------------------------
# config: artifact_db_path derivation
# ---------------------------------------------------------------------------


def test_runtime_config_artifact_db_path_defaults() -> None:
    runtime = RuntimeConfig.for_workspace("/tmp/example-workspace")
    workspace_root = Path("/tmp/example-workspace").resolve()
    assert runtime.artifact_db_path == workspace_root / ".task-state" / "mcp-artifacts.db"
    assert runtime.artifact_index_min_bytes == 4096
    assert runtime.artifact_index_min_lines == 80


# ---------------------------------------------------------------------------
# run_doctor: FTS5 availability check
# ---------------------------------------------------------------------------


def test_run_doctor_includes_fts5_check(tmp_path: Path) -> None:
    """run_doctor returns fts5_available=True and does not raise on CPython."""
    from unittest.mock import MagicMock, patch

    state_dir = tmp_path / ".task-state"
    runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
    mcp_server.configure_runtime(runtime)
    handoff_core.set_handoff_state(
        task_ref="doctor-fts5-test",
        objective="FTS5 check",
        status="in_progress",
    )

    mock_proc = MagicMock()
    mock_proc.stdout = json.dumps({"ok": True, "active_task": None})

    def _drain_and_return_tools(coro: object) -> list[str]:
        # Close the unawaited coroutine to suppress RuntimeWarning.
        if hasattr(coro, "close"):
            coro.close()
        return ["record_artifact", "search_artifacts"]

    with patch("agent_handoff_mcp.api.asyncio") as mock_async, \
         patch("agent_handoff_mcp.api.subprocess") as mock_sub:
        mock_async.run.side_effect = _drain_and_return_tools
        mock_sub.run.return_value = mock_proc
        result = mcp_server.run_doctor(runtime)

    assert result["ok"] is True
    assert result["checks"]["fts5_available"] is True
    assert "artifact_db_path" in result


# ---------------------------------------------------------------------------
# get_artifact_terms
# ---------------------------------------------------------------------------


def test_get_artifact_terms_returns_distinctive_words(isolated_env: dict) -> None:
    content = "\n".join(["authentication token validation security policy"] * 30)
    rec = _parse(handoff_core.record_artifact(
        source_kind="log",
        source_label="auth-policy-log",
        content=content,
        content_type="text/plain",
    ))
    assert rec["ok"] is True
    source_id = rec["source_id"]

    result = _parse(handoff_core.get_artifact_terms(source_id=source_id))
    assert result["ok"] is True
    assert result["source_id"] == source_id
    assert isinstance(result["terms"], list)
    assert len(result["terms"]) > 0
    # At least one domain word should appear
    assert any(t in ("authentication", "token", "validation", "security", "policy") for t in result["terms"])


def test_get_artifact_terms_lookup_by_label(isolated_env: dict) -> None:
    content = "\n".join(["database migration schema upgrade rollback"] * 30)
    handoff_core.record_artifact(
        source_kind="migration-log",
        source_label="db-upgrade-log",
        content=content,
        content_type="text/plain",
    )

    result = _parse(handoff_core.get_artifact_terms(
        task_ref="test-task",
        source_label="db-upgrade-log",
    ))
    assert result["ok"] is True
    assert isinstance(result["terms"], list)
    assert any(t in ("database", "migration", "schema", "upgrade", "rollback") for t in result["terms"])


def test_get_artifact_terms_returns_error_for_missing_source(isolated_env: dict) -> None:
    result = _parse(handoff_core.get_artifact_terms(source_id=99999))
    # Missing source_id returns empty terms rather than an error
    # (get_distinctive_terms returns [] for missing source_id)
    assert isinstance(result.get("terms"), list)
    assert result.get("terms") == []


def test_get_artifact_terms_requires_source_id_or_label(isolated_env: dict) -> None:
    result = _parse(handoff_core.get_artifact_terms())
    assert result["ok"] is False
    assert "source_id" in result["error"] or "source_label" in result["error"]


# ---------------------------------------------------------------------------
# purge_artifacts with lane_id and app_root
# ---------------------------------------------------------------------------


_PURGEABLE_CONTENT = "log line for purge testing\n" * 200


def _record(env: dict, source_kind: str, label: str, lane_id: str | None = None, app_root: str | None = None) -> None:
    handoff_core.record_artifact(
        source_kind=source_kind,
        source_label=label,
        content=_PURGEABLE_CONTENT,
        lane_id=lane_id,
        app_root=app_root,
    )


def test_purge_artifacts_by_lane_id_via_tool(isolated_env: dict) -> None:
    _record(isolated_env, "log", "log-lane-a-1", lane_id="lane-a")
    _record(isolated_env, "log", "log-lane-a-2", lane_id="lane-a")
    _record(isolated_env, "log", "log-lane-b-1", lane_id="lane-b")

    result = _parse(handoff_core.purge_artifacts(lane_id="lane-a"))
    assert result["ok"] is True
    assert result["purged_sources"] == 2

    remaining = _parse(handoff_core.list_artifact_sources(task_ref="test-task"))
    assert remaining["total"] == 1
    assert remaining["sources"][0]["lane_id"] == "lane-b"


def test_purge_artifacts_by_app_root_via_tool(isolated_env: dict) -> None:
    _record(isolated_env, "log", "svc-a-out", app_root="/apps/svc-a")
    _record(isolated_env, "log", "svc-b-out", app_root="/apps/svc-b")

    result = _parse(handoff_core.purge_artifacts(app_root="/apps/svc-a"))
    assert result["ok"] is True
    assert result["purged_sources"] == 1

    remaining = _parse(handoff_core.list_artifact_sources(task_ref="test-task"))
    assert remaining["total"] == 1
    assert remaining["sources"][0]["app_root"] == "/apps/svc-b"


def test_purge_artifacts_combined_filters_via_tool(isolated_env: dict) -> None:
    _record(isolated_env, "log", "keep-this", lane_id="lane-keep")
    _record(isolated_env, "log", "del-this", lane_id="lane-del")

    result = _parse(handoff_core.purge_artifacts(task_ref="test-task", lane_id="lane-del"))
    assert result["ok"] is True
    assert result["purged_sources"] == 1

    remaining = _parse(handoff_core.list_artifact_sources(task_ref="test-task"))
    labels = [s["source_label"] for s in remaining["sources"]]
    assert "keep-this" in labels
    assert "del-this" not in labels
