"""Deterministic edge-case tests for FTS5 query sanitization.

Covers the same surface as the previous hypothesis property tests:
- Non-blank text → phrase-quoted query
- Blank/whitespace-only → error contract
- _build_fts5_match_query → valid FTS5 MATCH for all edge cases
- Unicode, FTS5 operators, quoting, combining marks
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from agent_handoff_mcp import api as mcp_server
from agent_handoff_mcp import core as handoff_core
from agent_handoff_mcp.artifact_index import _FTS5_SPECIAL_RE, _build_fts5_match_query
from agent_handoff_mcp.config import RuntimeConfig
from agent_handoff_mcp.core import _FTS5_CONTROL_RE


def _parse(payload: str | dict) -> dict:
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def _new_fts_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE docs USING fts5(body)")
    conn.execute(
        "INSERT INTO docs(body) VALUES (?)",
        ("phrase query unicode cafe emoji test retry policy leader election",),
    )
    return conn


@contextmanager
def _isolated_runtime():
    with TemporaryDirectory(prefix="fts5-edge-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        state_dir = tmp_path / ".task-state"
        runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
        mcp_server.configure_runtime(runtime)
        handoff_core.set_handoff_state(
            task_ref="fts5-edge-test",
            objective="Validate FTS5 query sanitization",
            status="in_progress",
        )
        yield


# ---------------------------------------------------------------------------
# Phrase quoting: non-blank queries must produce a valid quoted FTS5 phrase
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "simple",
        "two words",
        'embedded "quotes" here',
        "NEAR(a b)",
        "col:value",
        "a + b",
        "a * b",
        "a OR b",
        "a AND b",
        "a NOT b",
        "trailing-hyphen-",
        "-leading-hyphen",
        "café",
        "😀 emoji 界",
        "cafe\u0301",
        "a" * 200,
    ],
)
def test_search_handoff_phrase_quotes_non_blank_terms(query: str) -> None:
    with _isolated_runtime():
        stripped = _FTS5_CONTROL_RE.sub(" ", query).strip()
        handoff_core.record_decision(session="fts5", decision=stripped)

        result = _parse(handoff_core.search_handoff(queries=[query], record_types=["decision"]))

        assert result["ok"] is True
        assert result["query"] == '"' + stripped.replace('"', '""') + '"'


# ---------------------------------------------------------------------------
# Blank queries: whitespace-only inputs must return the error contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "queries",
    [
        [" "],
        ["", ""],
        ["\t", "\n", "\r"],
        ["   ", " \t\n "],
    ],
)
def test_search_handoff_blank_queries_preserve_error_contract(queries: list[str]) -> None:
    with _isolated_runtime():
        result = _parse(handoff_core.search_handoff(queries=queries, record_types=["decision"]))

        assert result["ok"] is False
        assert result["error"] == "All query strings are empty after stripping."


# ---------------------------------------------------------------------------
# _build_fts5_match_query: edge cases that must produce valid or None output
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "queries",
    [
        # Single terms
        ["hello"],
        ["café"],
        ["😀"],
        # Embedded quotes
        ['say "hello"'],
        # FTS5 operators that must be escaped
        ["NEAR(a b)"],
        ["col:value"],
        ["a + b"],
        ["a * b"],
        # Multiple queries → OR join
        ["alpha", "beta"],
        ["one", "two", "three"],
        # Mixed blank and non-blank
        ["", "real query"],
        ["   ", "\t", "actual"],
        # Unicode combining marks
        ["cafe\u0301"],
        ["界 world"],
        # All blank → None
        ["", " ", "\t"],
        [""],
        # Long input
        ["word " * 50],
    ],
)
def test_build_fts5_match_query_edge_cases(queries: list[str]) -> None:
    match_query = _build_fts5_match_query(queries)
    cleaned_parts = [_FTS5_SPECIAL_RE.sub(" ", q).strip() for q in queries]
    cleaned_parts = [part for part in cleaned_parts if part]

    if not cleaned_parts:
        assert match_query is None
        return

    assert match_query is not None
    for cleaned in cleaned_parts:
        for term in cleaned.split():
            assert not _FTS5_SPECIAL_RE.search(term)
            escaped_term = term.replace('"', '""')
            assert f'"{escaped_term}"' in match_query

    if len(cleaned_parts) == 1:
        assert " OR " not in match_query
    else:
        assert " OR " in match_query

    # Must be valid FTS5 syntax
    with _new_fts_conn() as conn:
        conn.execute("SELECT count(*) FROM docs WHERE docs MATCH ?", (match_query,)).fetchone()


# ---------------------------------------------------------------------------
# Unicode and special characters through full search pipeline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "cafe",
        "café",
        "cafe\u0301",
        '"quoted"',
        "colon:value",
        "a-b-c",
        "😀🎉",
        "界世",
        'a "b" c',
        "- - -",
    ],
)
def test_search_handoff_phrase_query_handles_unicode_and_special_characters(query: str) -> None:
    with _isolated_runtime():
        stripped = query.strip()
        handoff_core.record_decision(session="fts5-unicode", decision=stripped)
        result = _parse(handoff_core.search_handoff(queries=[query], record_types=["decision"]))

        assert result["ok"] is True
        assert result["query"] == '"' + stripped.replace('"', '""') + '"'
