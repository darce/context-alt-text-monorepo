"""Unit tests for artifact_index: chunking, dedupe, search, and snippets."""

from __future__ import annotations

import sqlite3
import textwrap
from pathlib import Path

import pytest

from agent_handoff_mcp.artifact_index import (
    ARTIFACT_SCHEMA_SQL,
    check_fts5_available,
    chunk_content,
    chunk_json,
    chunk_markdown,
    chunk_plaintext,
    get_artifact_db_connection,
    get_artifact_source,
    list_artifact_sources,
    maybe_record_artifact,
    purge_artifacts,
    search_artifacts,
    upsert_source,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def artifact_db(tmp_path: Path) -> Path:
    """Return a path to a fresh temporary sidecar artifact database."""
    return tmp_path / ".task-state" / "mcp-artifacts.db"


# ---------------------------------------------------------------------------
# FTS5 availability
# ---------------------------------------------------------------------------


def test_check_fts5_available_returns_true_on_standard_python() -> None:
    # System Python on macOS 10.15+ and major Linux distros bundle FTS5.
    with sqlite3.connect(":memory:") as conn:
        assert check_fts5_available(conn) is True


# ---------------------------------------------------------------------------
# chunk_markdown
# ---------------------------------------------------------------------------


def test_chunk_markdown_single_section() -> None:
    content = "# Title\nSome body text."
    chunks = chunk_markdown(content, "doc")
    assert len(chunks) == 1
    title, body = chunks[0]
    assert title == "Title"
    assert "Some body text" in body


def test_chunk_markdown_multiple_headings() -> None:
    content = textwrap.dedent("""\
        # Intro
        Intro text.

        ## Setup
        Setup text.

        ### Details
        Detail text.
    """)
    chunks = chunk_markdown(content, "doc")
    titles = [t for t, _ in chunks]
    assert "Intro" in titles
    assert "Setup" in titles
    assert "Details" in titles


def test_chunk_markdown_preamble_before_first_heading() -> None:
    content = "Some preamble.\n\n# Heading\nBody."
    chunks = chunk_markdown(content, "doc")
    # First chunk should be the preamble, second the heading section
    assert len(chunks) == 2
    assert chunks[0][0] == "doc"
    assert "preamble" in chunks[0][1]


def test_chunk_markdown_no_headings_returns_single_chunk() -> None:
    content = "Just plain text without any headings."
    chunks = chunk_markdown(content, "source")
    assert len(chunks) == 1
    assert chunks[0][0] == "source"
    assert "plain text" in chunks[0][1]


def test_chunk_markdown_empty_content_returns_empty() -> None:
    assert chunk_markdown("", "source") == []
    assert chunk_markdown("   \n  ", "source") == []


# ---------------------------------------------------------------------------
# chunk_plaintext
# ---------------------------------------------------------------------------


def test_chunk_plaintext_single_part_for_small_content() -> None:
    content = "line1\nline2\nline3"
    chunks = chunk_plaintext(content, "log", lines_per_chunk=50)
    assert len(chunks) == 1
    assert chunks[0][0] == "log"
    assert "line1" in chunks[0][1]


def test_chunk_plaintext_multiple_parts_for_large_content() -> None:
    lines = [f"line {i}" for i in range(120)]
    content = "\n".join(lines)
    chunks = chunk_plaintext(content, "output", lines_per_chunk=50)
    assert len(chunks) == 3
    # Titles include part numbers when there are multiple parts
    assert "part 1/3" in chunks[0][0]
    assert "part 3/3" in chunks[2][0]


def test_chunk_plaintext_skips_blank_groups() -> None:
    content = "\n\n\n"
    chunks = chunk_plaintext(content, "empty")
    assert chunks == []


# ---------------------------------------------------------------------------
# chunk_json
# ---------------------------------------------------------------------------


def test_chunk_json_dict_top_level_keys() -> None:
    import json

    data = {"key1": "value1", "key2": {"nested": True}}
    chunks = chunk_json(json.dumps(data), "payload")
    titles = {t for t, _ in chunks}
    assert "payload.key1" in titles
    assert "payload.key2" in titles


def test_chunk_json_list_items() -> None:
    import json

    data = [{"id": 1}, {"id": 2}]
    chunks = chunk_json(json.dumps(data), "items")
    assert len(chunks) == 2
    assert chunks[0][0] == "items[0]"
    assert chunks[1][0] == "items[1]"


def test_chunk_json_invalid_falls_back_to_plaintext() -> None:
    chunks = chunk_json("not valid json {{{", "raw")
    # Falls back to plaintext chunking
    assert len(chunks) >= 1
    assert "not valid json" in chunks[0][1]


# ---------------------------------------------------------------------------
# chunk_content dispatch
# ---------------------------------------------------------------------------


def test_chunk_content_dispatches_markdown() -> None:
    content = "# Heading\nBody."
    chunks = chunk_content(content, "text/markdown", "doc")
    assert chunks[0][0] == "Heading"


def test_chunk_content_dispatches_json() -> None:
    import json

    chunks = chunk_content(json.dumps({"a": 1}), "application/json", "payload")
    assert any(".a" in t for t, _ in chunks)


def test_chunk_content_dispatches_plaintext_by_default() -> None:
    chunks = chunk_content("line1\nline2", "text/plain", "log")
    assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# upsert_source and dedupe
# ---------------------------------------------------------------------------


def test_upsert_source_inserts_new_source(artifact_db: Path) -> None:
    result = upsert_source(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="log",
        source_label="pytest-output",
        content_type="text/plain",
        summary="Test run output",
        content="PASSED test_foo\nPASSED test_bar\n" + "line\n" * 100,
        artifact_db_path=artifact_db,
    )
    assert result["was_updated"] is True
    assert result["source_id"] is not None
    assert result["chunk_count"] > 0
    assert result["source_label"] == "pytest-output"


def test_upsert_source_dedupes_identical_content(artifact_db: Path) -> None:
    content = "identical content\n" * 100
    kwargs = dict(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="doc",
        source_label="readme",
        content_type="text/plain",
        summary=None,
        content=content,
        artifact_db_path=artifact_db,
    )
    first = upsert_source(**kwargs)
    second = upsert_source(**kwargs)
    assert first["was_updated"] is True
    assert second["was_updated"] is False
    assert first["source_id"] == second["source_id"]


def test_upsert_source_reindexes_on_content_change(artifact_db: Path) -> None:
    base_kwargs = dict(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="doc",
        source_label="notes",
        content_type="text/markdown",
        summary=None,
        artifact_db_path=artifact_db,
    )
    first = upsert_source(content="# First\nOriginal content.\n" * 20, **base_kwargs)
    second = upsert_source(content="# Second\nUpdated content.\n" * 20, **base_kwargs)
    assert second["was_updated"] is True
    assert second["source_id"] == first["source_id"]

    # Old chunks should be replaced; search finds the new content
    hits = search_artifacts(
        queries=["Updated content"],
        task_ref="task-1",
        artifact_db_path=artifact_db,
    )
    assert any("Updated" in h["snippet"] or h["title"] == "Second" for h in hits)


# ---------------------------------------------------------------------------
# search_artifacts
# ---------------------------------------------------------------------------


def _seed_artifacts(artifact_db: Path) -> None:
    """Insert a set of known artifacts for search tests."""
    upsert_source(
        task_ref="task-alpha",
        lane_id="backend",
        app_root="apps/svc",
        source_kind="test-output",
        source_label="pytest-run-1",
        content_type="text/plain",
        summary="Backend test run",
        content="PASSED test_migration\nFAILED test_schema\nError: column missing\n" * 30,
        artifact_db_path=artifact_db,
    )
    upsert_source(
        task_ref="task-alpha",
        lane_id="frontend",
        app_root="apps/wp",
        source_kind="test-output",
        source_label="vitest-run-1",
        content_type="text/plain",
        summary="Frontend test run",
        content="PASS src/components/Widget.test.tsx\nFAIL src/hooks/useSync.test.tsx\n" * 30,
        artifact_db_path=artifact_db,
    )
    upsert_source(
        task_ref="task-beta",
        lane_id=None,
        app_root=None,
        source_kind="http-response",
        source_label="api-snapshot",
        content_type="application/json",
        summary="API snapshot",
        content='{"status": "ok", "version": "1.2.3", "data": {"items": []}}\n' * 20,
        artifact_db_path=artifact_db,
    )


def test_search_artifacts_returns_relevant_hits(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["schema missing"],
        artifact_db_path=artifact_db,
    )
    assert len(hits) > 0
    assert any("schema" in h["snippet"].lower() or "schema" in h["title"].lower() for h in hits)


def test_search_artifacts_scoped_by_task_ref(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["test"],
        task_ref="task-beta",
        artifact_db_path=artifact_db,
    )
    # Only task-beta artifacts should be returned
    for h in hits:
        assert h["task_ref"] == "task-beta"


def test_search_artifacts_scoped_by_lane_id(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["FAILED"],
        task_ref="task-alpha",
        lane_id="backend",
        artifact_db_path=artifact_db,
    )
    for h in hits:
        assert h["lane_id"] == "backend"


def test_search_artifacts_scoped_by_source_kind(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["status ok"],
        source_kind="http-response",
        artifact_db_path=artifact_db,
    )
    for h in hits:
        assert h["source_kind"] == "http-response"


def test_search_artifacts_empty_queries_returns_empty(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    assert search_artifacts(queries=[], artifact_db_path=artifact_db) == []
    assert search_artifacts(queries=["  "], artifact_db_path=artifact_db) == []


def test_search_artifacts_no_match_returns_empty(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["xyzzynonexistentterm12345"],
        artifact_db_path=artifact_db,
    )
    assert hits == []


def test_search_artifacts_respects_limit(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["test"],
        limit=1,
        artifact_db_path=artifact_db,
    )
    assert len(hits) <= 1


def test_search_artifacts_hits_include_snippet(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    hits = search_artifacts(
        queries=["migration"],
        artifact_db_path=artifact_db,
    )
    assert len(hits) > 0
    for h in hits:
        assert "snippet" in h
        assert isinstance(h["snippet"], str)


def test_search_artifacts_hits_include_source_label(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    # "migration" appears in the seeded backend test output body content
    hits = search_artifacts(
        queries=["migration"],
        task_ref="task-alpha",
        artifact_db_path=artifact_db,
    )
    assert len(hits) > 0
    for h in hits:
        assert h["source_label"] != ""


# ---------------------------------------------------------------------------
# get_artifact_source
# ---------------------------------------------------------------------------


def test_get_artifact_source_by_id(artifact_db: Path) -> None:
    result = upsert_source(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="doc",
        source_label="readme",
        content_type="text/plain",
        summary="A readme",
        content="Content here\n" * 10,
        artifact_db_path=artifact_db,
    )
    source = get_artifact_source(
        source_id=result["source_id"], artifact_db_path=artifact_db
    )
    assert source is not None
    assert source["source_label"] == "readme"
    assert source["task_ref"] == "task-1"
    assert "chunk_count" in source
    assert "chunks" in source
    assert isinstance(source["chunks"], list)
    assert len(source["chunks"]) == source["chunk_count"]
    if source["chunks"]:
        first = source["chunks"][0]
        assert "chunk_order" in first
        assert "title" in first
        assert "body" in first
        assert first["chunk_order"] == 1


def test_get_artifact_source_by_task_and_label(artifact_db: Path) -> None:
    upsert_source(
        task_ref="task-X",
        lane_id=None,
        app_root=None,
        source_kind="doc",
        source_label="notes",
        content_type="text/markdown",
        summary=None,
        content="# Notes\nSome notes\n" * 5,
        artifact_db_path=artifact_db,
    )
    source = get_artifact_source(
        task_ref="task-X", source_label="notes", artifact_db_path=artifact_db
    )
    assert source is not None
    assert source["source_label"] == "notes"
    assert "chunks" in source
    assert isinstance(source["chunks"], list)


def test_get_artifact_source_not_found_returns_none(artifact_db: Path) -> None:
    source = get_artifact_source(
        source_id=99999, artifact_db_path=artifact_db
    )
    assert source is None


def test_get_artifact_source_no_args_returns_none(artifact_db: Path) -> None:
    source = get_artifact_source(artifact_db_path=artifact_db)
    assert source is None


# ---------------------------------------------------------------------------
# list_artifact_sources
# ---------------------------------------------------------------------------


def test_list_artifact_sources_no_filter(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    rows = list_artifact_sources(artifact_db_path=artifact_db)
    assert len(rows) == 3


def test_list_artifact_sources_filter_by_task_ref(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    rows = list_artifact_sources(task_ref="task-alpha", artifact_db_path=artifact_db)
    assert len(rows) == 2
    for r in rows:
        assert r["task_ref"] == "task-alpha"


def test_list_artifact_sources_filter_by_source_kind(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    rows = list_artifact_sources(source_kind="http-response", artifact_db_path=artifact_db)
    assert len(rows) == 1
    assert rows[0]["source_label"] == "api-snapshot"


def test_list_artifact_sources_pagination(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    first_page = list_artifact_sources(limit=2, offset=0, artifact_db_path=artifact_db)
    second_page = list_artifact_sources(limit=2, offset=2, artifact_db_path=artifact_db)
    assert len(first_page) == 2
    assert len(second_page) == 1


# ---------------------------------------------------------------------------
# purge_artifacts
# ---------------------------------------------------------------------------


def test_purge_artifacts_by_task_ref(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    result = purge_artifacts(task_ref="task-alpha", artifact_db_path=artifact_db)
    assert result["ok"] is True
    assert result["purged_sources"] == 2
    remaining = list_artifact_sources(artifact_db_path=artifact_db)
    assert len(remaining) == 1
    assert remaining[0]["task_ref"] == "task-beta"


def test_purge_artifacts_by_age(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    # Age of 0 seconds: nothing is older than "now", so no purge
    result = purge_artifacts(older_than_days=0, artifact_db_path=artifact_db)
    assert result["ok"] is True
    # Very large age should also purge nothing (records were just created)
    result2 = purge_artifacts(older_than_days=3650, artifact_db_path=artifact_db)
    assert result2["purged_sources"] == 0


def test_purge_artifacts_no_conditions_is_noop(artifact_db: Path) -> None:
    _seed_artifacts(artifact_db)
    result = purge_artifacts(artifact_db_path=artifact_db)
    assert result["purged_sources"] == 0
    assert result["ok"] is True
    assert len(list_artifact_sources(artifact_db_path=artifact_db)) == 3


def test_purge_artifacts_removes_fts_chunks(artifact_db: Path) -> None:
    result = upsert_source(
        task_ref="task-cleanup",
        lane_id=None,
        app_root=None,
        source_kind="log",
        source_label="big-log",
        content_type="text/plain",
        summary=None,
        content="some log line\n" * 100,
        artifact_db_path=artifact_db,
    )
    assert result["chunk_count"] > 0

    purge_artifacts(task_ref="task-cleanup", artifact_db_path=artifact_db)

    # After purge, source should be gone
    source = get_artifact_source(
        source_id=result["source_id"], artifact_db_path=artifact_db
    )
    assert source is None

    # And search should return no results
    hits = search_artifacts(
        queries=["log line"],
        task_ref="task-cleanup",
        artifact_db_path=artifact_db,
    )
    assert hits == []


# ---------------------------------------------------------------------------
# maybe_record_artifact
# ---------------------------------------------------------------------------


def test_maybe_record_artifact_indexes_large_content(artifact_db: Path) -> None:
    large = "line\n" * 100
    result = maybe_record_artifact(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="log",
        source_label="big-output",
        content=large,
        content_type="text/plain",
        summary=None,
        artifact_db_path=artifact_db,
        min_bytes=10,
        min_lines=10,
    )
    assert result is not None
    assert result["was_updated"] is True


def test_maybe_record_artifact_skips_small_content(artifact_db: Path) -> None:
    small = "tiny"
    result = maybe_record_artifact(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="log",
        source_label="small-output",
        content=small,
        content_type="text/plain",
        summary=None,
        artifact_db_path=artifact_db,
        min_bytes=4096,
        min_lines=80,
    )
    assert result is None


def test_maybe_record_artifact_indexed_on_line_threshold(artifact_db: Path) -> None:
    # 85 lines but fewer than min_bytes - should still be indexed (OR logic: either threshold)
    # The implementation uses AND logic: skip only if BOTH thresholds fail
    content = "short\n" * 85  # 85 lines, ~510 bytes (< 4096)
    result = maybe_record_artifact(
        task_ref="task-1",
        lane_id=None,
        app_root=None,
        source_kind="log",
        source_label="lines-threshold-output",
        content=content,
        content_type="text/plain",
        summary=None,
        artifact_db_path=artifact_db,
        min_bytes=4096,
        min_lines=80,
    )
    # 85 lines >= min_lines (80), so should be indexed despite being under min_bytes
    assert result is not None


# ---------------------------------------------------------------------------
# Schema bootstrap idempotency
# ---------------------------------------------------------------------------


def test_schema_bootstrap_is_idempotent(artifact_db: Path) -> None:
    # Open connection twice; schema should succeed both times without error
    conn1 = get_artifact_db_connection(artifact_db)
    conn1.close()
    conn2 = get_artifact_db_connection(artifact_db)
    tables = {
        row[0]
        for row in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'shadow')"
        ).fetchall()
    }
    conn2.close()
    assert "artifact_sources" in tables
