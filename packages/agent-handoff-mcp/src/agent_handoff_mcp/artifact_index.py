"""Sidecar artifact indexing for agent-handoff-mcp.

Maintains a separate SQLite/FTS5 database (.task-state/mcp-artifacts.db) so
large evidence blobs can be stored and later retrieved by scoped full-text
search without polluting the handoff snapshot or prompt context.
"""

from __future__ import annotations

import hashlib
import json as _json
import re
import sqlite3
from pathlib import Path


ARTIFACT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS artifact_sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    task_ref      TEXT NOT NULL,
    lane_id       TEXT,
    app_root      TEXT,
    source_kind   TEXT NOT NULL,
    source_label  TEXT NOT NULL,
    content_type  TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    metadata_json TEXT,
    summary       TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(task_ref, lane_id, source_kind, source_label)
);

CREATE VIRTUAL TABLE IF NOT EXISTS artifact_chunks_fts USING fts5(
    title,
    body,
    source_id    UNINDEXED,
    task_ref     UNINDEXED,
    lane_id      UNINDEXED,
    app_root     UNINDEXED,
    source_kind  UNINDEXED,
    content_type UNINDEXED,
    tokenize='porter unicode61'
);
"""


def check_fts5_available(conn: sqlite3.Connection) -> bool:
    """Return True if the connected SQLite build supports FTS5."""
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_probe USING fts5(body)"
        )
        conn.execute("DROP TABLE IF EXISTS _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def get_artifact_db_connection(artifact_db_path: Path) -> sqlite3.Connection:
    """Open (or create) the sidecar artifact database, apply the schema, and return the connection.

    Raises RuntimeError if the local SQLite build does not support FTS5.
    """
    artifact_db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(artifact_db_path))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        if not check_fts5_available(conn):
            raise RuntimeError(
                "SQLite FTS5 extension is not available on this system. "
                "agent-handoff-mcp artifact indexing requires FTS5. "
                "Rebuild SQLite with SQLITE_ENABLE_FTS5 or use a Python distribution "
                "that bundles FTS5 (e.g. system Python on macOS 10.15+ or major Linux distros)."
            )
        conn.executescript(ARTIFACT_SCHEMA_SQL)
    except Exception:
        conn.close()
        raise
    return conn


# ---------------------------------------------------------------------------
# Chunkers
# ---------------------------------------------------------------------------

_FTS5_SPECIAL_RE = re.compile(r'["^*+\-():]')


def _build_fts5_match_query(queries: list[str]) -> str | None:
    """Turn a list of query strings into a single FTS5 MATCH expression.

    Each query string is sanitised and treated as an AND of its individual
    words. Multiple queries are OR-joined so any match wins.
    Words within a single query must all appear in the same chunk (FTS5 AND).
    """
    parts: list[str] = []
    for q in queries:
        # Strip FTS5 metacharacters so callers don't need FTS5 syntax knowledge
        cleaned = _FTS5_SPECIAL_RE.sub(" ", q).strip()
        if cleaned:
            parts.append(cleaned)
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return " OR ".join(f"({p})" for p in parts)


_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)


def chunk_markdown(content: str, source_label: str) -> list[tuple[str, str]]:
    """Split markdown text into (title, body) tuples on H1-H3 headings."""
    positions = [(m.start(), m.group(2).strip()) for m in _HEADING_RE.finditer(content)]
    if not positions:
        stripped = content.strip()
        return [(source_label, stripped)] if stripped else []

    chunks: list[tuple[str, str]] = []

    # Content before the first heading
    first_start = positions[0][0]
    if first_start > 0:
        preamble = content[:first_start].strip()
        if preamble:
            chunks.append((source_label, preamble))

    for i, (start, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(content)
        body = content[start:end].strip()
        if body:
            chunks.append((title, body))

    return chunks if chunks else [(source_label, content.strip())]


def chunk_plaintext(
    content: str, source_label: str, lines_per_chunk: int = 50
) -> list[tuple[str, str]]:
    """Split plaintext into (title, body) chunks of up to *lines_per_chunk* lines."""
    lines = content.splitlines()
    if not lines:
        return []

    total_parts = max(1, (len(lines) + lines_per_chunk - 1) // lines_per_chunk)
    chunks: list[tuple[str, str]] = []
    for idx in range(0, len(lines), lines_per_chunk):
        group = lines[idx : idx + lines_per_chunk]
        body = "\n".join(group).strip()
        if not body:
            continue
        part_num = idx // lines_per_chunk + 1
        title = (
            f"{source_label} (part {part_num}/{total_parts})"
            if total_parts > 1
            else source_label
        )
        chunks.append((title, body))

    return chunks


def chunk_json(content: str, source_label: str) -> list[tuple[str, str]]:
    """Split JSON into chunks: one per top-level dict key or list item."""
    try:
        data = _json.loads(content)
    except (ValueError, TypeError):
        return chunk_plaintext(content, source_label)

    chunks: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            body = _json.dumps(value, indent=2, ensure_ascii=False)
            if body:
                chunks.append((f"{source_label}.{key}", body))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            body = _json.dumps(item, indent=2, ensure_ascii=False)
            if body:
                chunks.append((f"{source_label}[{i}]", body))
    else:
        stripped = content.strip()
        if stripped:
            chunks.append((source_label, stripped))

    return chunks if chunks else chunk_plaintext(content, source_label)


def chunk_content(
    content: str, content_type: str, source_label: str
) -> list[tuple[str, str]]:
    """Dispatch to the appropriate chunker based on *content_type*."""
    ct = (content_type or "").lower()
    if "markdown" in ct or ct in ("text/md", "md", "text/markdown"):
        return chunk_markdown(content, source_label)
    if "json" in ct:
        return chunk_json(content, source_label)
    return chunk_plaintext(content, source_label)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


def upsert_source(
    *,
    task_ref: str,
    lane_id: str | None,
    app_root: str | None,
    source_kind: str,
    source_label: str,
    content_type: str,
    summary: str | None,
    content: str,
    metadata: dict | None = None,
    artifact_db_path: Path,
) -> dict:
    """Insert or replace an artifact source and re-index its FTS5 chunks.

    If the content hash matches an existing source, the source and its chunks
    are left unchanged (dedupe-on-reindex). Returns a result dict with
    ``source_id``, ``source_label``, ``was_updated``, and ``chunk_count``.
    """
    conn = get_artifact_db_connection(artifact_db_path)
    try:
        with conn:
            new_hash = _content_hash(content)
            existing = conn.execute(
                """
                SELECT id, content_hash FROM artifact_sources
                WHERE task_ref = ? AND lane_id IS ? AND source_kind = ? AND source_label = ?
                """,
                [task_ref, lane_id, source_kind, source_label],
            ).fetchone()

            if existing and existing["content_hash"] == new_hash:
                chunk_count = conn.execute(
                    "SELECT COUNT(*) FROM artifact_chunks_fts WHERE source_id = ?",
                    [str(existing["id"])],
                ).fetchone()[0]
                result: dict = {
                    "source_id": existing["id"],
                    "source_label": source_label,
                    "was_updated": False,
                    "chunk_count": chunk_count,
                }
            else:
                metadata_json = _json.dumps(metadata) if metadata else None
                if existing:
                    conn.execute(
                        """
                        UPDATE artifact_sources
                        SET content_type = ?, content_hash = ?, metadata_json = ?,
                            summary = ?, updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        [
                            content_type,
                            new_hash,
                            metadata_json,
                            summary,
                            existing["id"],
                        ],
                    )
                    source_id: int = existing["id"]
                else:
                    source_id = conn.execute(
                        """
                        INSERT INTO artifact_sources
                            (task_ref, lane_id, app_root, source_kind, source_label,
                             content_type, content_hash, metadata_json, summary)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            task_ref,
                            lane_id,
                            app_root,
                            source_kind,
                            source_label,
                            content_type,
                            new_hash,
                            metadata_json,
                            summary,
                        ],
                    ).lastrowid  # type: ignore[assignment]

                # Delete stale FTS chunks and rebuild
                conn.execute(
                    "DELETE FROM artifact_chunks_fts WHERE source_id = ?",
                    [str(source_id)],
                )
                chunks = chunk_content(content, content_type, source_label)
                conn.executemany(
                    """
                    INSERT INTO artifact_chunks_fts
                        (title, body, source_id, task_ref, lane_id, app_root,
                         source_kind, content_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            title,
                            body,
                            str(source_id),
                            task_ref,
                            lane_id or "",
                            app_root or "",
                            source_kind,
                            content_type,
                        )
                        for title, body in chunks
                    ],
                )
                result = {
                    "source_id": source_id,
                    "source_label": source_label,
                    "was_updated": True,
                    "chunk_count": len(chunks),
                }
    finally:
        conn.close()

    return result


def search_artifacts(
    *,
    queries: list[str],
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    source_kind: str | None = None,
    content_type: str | None = None,
    limit: int = 10,
    artifact_db_path: Path,
) -> list[dict]:
    """Search artifact chunks by relevance with optional scope filters.

    Returns a list of hit dicts containing source metadata, chunk title,
    BM25 rank, and a compact highlighted snippet.
    """
    sanitized = [q.replace('"', '""').strip() for q in queries if q and q.strip()]
    if not sanitized:
        return []

    match_query = _build_fts5_match_query(queries)
    if match_query is None:
        return []

    conn = get_artifact_db_connection(artifact_db_path)
    try:
        extra_filters: list[str] = []
        params: list[object] = [match_query]

        if task_ref:
            extra_filters.append("task_ref = ?")
            params.append(task_ref)
        if lane_id:
            extra_filters.append("lane_id = ?")
            params.append(lane_id)
        if app_root:
            extra_filters.append("app_root = ?")
            params.append(app_root)
        if source_kind:
            extra_filters.append("source_kind = ?")
            params.append(source_kind)
        if content_type:
            extra_filters.append("content_type = ?")
            params.append(content_type)

        where_parts = ["artifact_chunks_fts MATCH ?"]
        where_parts.extend(extra_filters)
        where_clause = " AND ".join(where_parts)

        params.append(limit)
        fts_sql = f"""
            SELECT source_id, task_ref, lane_id, app_root, source_kind, content_type, title,
                   snippet(artifact_chunks_fts, 1, '**', '**', '...', 20) AS snippet,
                   rank
            FROM artifact_chunks_fts
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
        """
        rows = conn.execute(fts_sql, params).fetchall()
        if not rows:
            return []

        # Enrich with source_label and summary from the metadata table
        source_ids = list({r["source_id"] for r in rows})
        placeholders = ",".join("?" * len(source_ids))
        source_map: dict[str, dict] = {
            str(r["id"]): {"source_label": r["source_label"], "summary": r["summary"]}
            for r in conn.execute(
                f"SELECT id, source_label, summary FROM artifact_sources WHERE id IN ({placeholders})",
                [int(sid) for sid in source_ids],
            ).fetchall()
        }

        results: list[dict] = []
        for r in rows:
            meta = source_map.get(r["source_id"], {})
            results.append(
                {
                    "source_id": int(r["source_id"]),
                    "source_label": meta.get("source_label", ""),
                    "source_summary": meta.get("summary") or "",
                    "task_ref": r["task_ref"],
                    "lane_id": r["lane_id"] or None,
                    "app_root": r["app_root"] or None,
                    "source_kind": r["source_kind"],
                    "content_type": r["content_type"],
                    "title": r["title"],
                    "snippet": r["snippet"],
                    "rank": r["rank"],
                }
            )
        return results
    finally:
        conn.close()


def get_artifact_source(
    *,
    source_id: int | None = None,
    task_ref: str | None = None,
    source_label: str | None = None,
    artifact_db_path: Path,
) -> dict | None:
    """Return the full artifact source record, or None if not found.

    Lookup priority: *source_id* > (*task_ref* + *source_label*).
    """
    conn = get_artifact_db_connection(artifact_db_path)
    try:
        if source_id is not None:
            row = conn.execute(
                "SELECT * FROM artifact_sources WHERE id = ?", [source_id]
            ).fetchone()
        elif task_ref and source_label:
            row = conn.execute(
                """
                SELECT * FROM artifact_sources
                WHERE task_ref = ? AND source_label = ?
                LIMIT 1
                """,
                [task_ref, source_label],
            ).fetchone()
        else:
            return None

        if row is None:
            return None

        result = dict(row)
        if result.get("metadata_json"):
            try:
                result["metadata"] = _json.loads(result["metadata_json"])
            except (ValueError, TypeError):
                result["metadata"] = None
        else:
            result["metadata"] = None

        chunk_rows = conn.execute(
            "SELECT rowid, title, body FROM artifact_chunks_fts WHERE source_id = ? ORDER BY rowid",
            [str(result["id"])],
        ).fetchall()
        result["chunk_count"] = len(chunk_rows)
        result["chunks"] = [
            {"chunk_order": i + 1, "title": row["title"], "body": row["body"]}
            for i, row in enumerate(chunk_rows)
        ]
        return result
    finally:
        conn.close()


def list_artifact_sources(
    *,
    task_ref: str | None = None,
    lane_id: str | None = None,
    app_root: str | None = None,
    source_kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
    artifact_db_path: Path,
) -> list[dict]:
    """Return a paginated list of artifact sources matching the given filters."""
    conn = get_artifact_db_connection(artifact_db_path)
    try:
        conditions: list[str] = []
        params: list[object] = []
        if task_ref:
            conditions.append("task_ref = ?")
            params.append(task_ref)
        if lane_id:
            conditions.append("lane_id = ?")
            params.append(lane_id)
        if app_root:
            conditions.append("app_root = ?")
            params.append(app_root)
        if source_kind:
            conditions.append("source_kind = ?")
            params.append(source_kind)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params += [limit, offset]
        rows = conn.execute(
            f"SELECT * FROM artifact_sources {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def purge_artifacts(
    *,
    task_ref: str | None = None,
    older_than_days: int | None = None,
    artifact_db_path: Path,
) -> dict:
    """Delete artifact sources and their FTS chunks.

    *task_ref*: delete all sources for that task.
    *older_than_days*: delete sources whose ``updated_at`` is older than N days.
    Both conditions are ANDed when provided. At least one must be given.
    """
    conditions: list[str] = []
    params: list[object] = []
    if task_ref:
        conditions.append("task_ref = ?")
        params.append(task_ref)
    if older_than_days is not None:
        conditions.append("updated_at < datetime('now', ?)")
        params.append(f"-{older_than_days} days")
    if not conditions:
        return {"purged_sources": 0, "ok": True}

    conn = get_artifact_db_connection(artifact_db_path)
    try:
        with conn:
            where = "WHERE " + " AND ".join(conditions)
            ids = [
                str(r[0])
                for r in conn.execute(
                    f"SELECT id FROM artifact_sources {where}", params
                ).fetchall()
            ]
            if not ids:
                return {"purged_sources": 0, "ok": True}

            id_placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM artifact_chunks_fts WHERE source_id IN ({id_placeholders})",
                ids,
            )
            conn.execute(
                f"DELETE FROM artifact_sources WHERE id IN ({id_placeholders})",
                [int(i) for i in ids],
            )
    finally:
        conn.close()

    return {"purged_sources": len(ids), "ok": True}


def maybe_record_artifact(
    *,
    task_ref: str,
    lane_id: str | None,
    app_root: str | None,
    source_kind: str,
    source_label: str,
    content: str,
    content_type: str,
    summary: str | None,
    artifact_db_path: Path,
    min_bytes: int = 4096,
    min_lines: int = 80,
) -> dict | None:
    """Index *content* only when it meets the configured size thresholds.

    Returns the upsert result dict if indexed, or None if below threshold.
    """
    if len(content.encode("utf-8")) < min_bytes and content.count("\n") < min_lines:
        return None

    return upsert_source(
        task_ref=task_ref,
        lane_id=lane_id,
        app_root=app_root,
        source_kind=source_kind,
        source_label=source_label,
        content_type=content_type,
        summary=summary,
        content=content,
        artifact_db_path=artifact_db_path,
    )
