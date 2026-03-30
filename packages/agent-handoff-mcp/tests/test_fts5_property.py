from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

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
    with TemporaryDirectory(prefix="fts5-property-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        state_dir = tmp_path / ".task-state"
        runtime = RuntimeConfig.for_workspace(tmp_path, state_dir=state_dir)
        mcp_server.configure_runtime(runtime)
        handoff_core.set_handoff_state(
            task_ref="fts5-property-test",
            objective="Validate FTS5 query sanitization",
            status="in_progress",
        )
        yield


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text().filter(lambda value: bool(_FTS5_CONTROL_RE.sub(" ", value).strip())))
def test_search_handoff_phrase_quotes_non_blank_terms(
    query: str,
) -> None:
    with _isolated_runtime():
        stripped = _FTS5_CONTROL_RE.sub(" ", query).strip()
        handoff_core.record_decision(session="fts5", decision=stripped)

        result = _parse(handoff_core.search_handoff(queries=[query], record_types=["decision"]))

        assert result["ok"] is True
        assert result["query"] == '"' + stripped.replace('"', '""') + '"'


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.lists(st.text(alphabet=[" ", "\t", "\n", "\r"]), min_size=1, max_size=4))
def test_search_handoff_blank_queries_preserve_error_contract(
    queries: list[str],
) -> None:
    with _isolated_runtime():
        result = _parse(handoff_core.search_handoff(queries=queries, record_types=["decision"]))

        assert result["ok"] is False
        assert result["error"] == "All query strings are empty after stripping."


@settings(max_examples=100, deadline=None)
@given(st.lists(st.text(), min_size=1, max_size=4))
def test_build_fts5_match_query_executes_without_error(queries: list[str]) -> None:
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

    with _new_fts_conn() as conn:
        conn.execute("SELECT count(*) FROM docs WHERE docs MATCH ?", (match_query,)).fetchone()


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.text(alphabet=st.sampled_from(["c", "a", "f", "e", " ", '"', ":", "-", "😀", "界", "\u0301"]), min_size=1))
def test_search_handoff_phrase_query_handles_unicode_and_special_characters(
    query: str,
) -> None:
    with _isolated_runtime():
        if not query.strip():
            query = query + " cafe"

        stripped = query.strip()
        handoff_core.record_decision(session="fts5-unicode", decision=stripped)
        result = _parse(handoff_core.search_handoff(queries=[query], record_types=["decision"]))

        assert result["ok"] is True
        assert result["query"] == '"' + stripped.replace('"', '""') + '"'
