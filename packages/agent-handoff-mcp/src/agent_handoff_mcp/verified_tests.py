"""Verified test read surfaces."""

from __future__ import annotations

from ._shared import _envelope, _get_db_connection, _resolve_task_ref, _row_to_dict


def get_verified_tests(
    task_ref: str | None = None,
    lane_id: str | None = None,
    branch: str | None = None,
    commit_sha: str | None = None,
    passed: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List verified test rows with bounded filters and deterministic ordering.

    Args:
        task_ref: Optional task scope. Defaults to the active task.
        lane_id: Optional lane filter.
        branch: Optional branch filter.
        commit_sha: Optional commit SHA filter.
        passed: Optional pass/fail filter.
        limit: Maximum rows to return; clamped to [1, 200].
        offset: Pagination offset; negative values are normalized to 0.

    Returns:
        v2 envelope containing ordered verified test rows and pagination metadata.
    """

    clamped_limit = max(1, min(int(limit), 200))
    clamped_offset = max(0, int(offset))

    with _get_db_connection() as conn:
        resolved_task_ref = _resolve_task_ref(conn, task_ref)
        where_parts = ["task_ref = ?"]
        params: list[object] = [resolved_task_ref]

        if lane_id is not None:
            where_parts.append("lane_id = ?")
            params.append(lane_id)
        if branch is not None:
            where_parts.append("branch = ?")
            params.append(branch)
        if commit_sha is not None:
            where_parts.append("commit_sha = ?")
            params.append(commit_sha)
        if passed is not None:
            where_parts.append("passed = ?")
            params.append(1 if passed else 0)

        where_sql = " AND ".join(where_parts)
        total = int(conn.execute(f"SELECT COUNT(*) FROM verified_tests WHERE {where_sql}", params).fetchone()[0])
        rows = []
        for row in conn.execute(
            f"""
            SELECT *
            FROM verified_tests
            WHERE {where_sql}
            ORDER BY verified_at DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            (*params, clamped_limit, clamped_offset),
        ).fetchall():
            payload = _row_to_dict(row)
            if payload is None:
                continue
            if "passed" in payload:
                payload["passed"] = bool(payload["passed"])
            rows.append(payload)

        return _envelope(
            ok=True,
            tool="get_verified_tests",
            data={
                "task_ref": resolved_task_ref,
                "lane_id": lane_id,
                "branch": branch,
                "commit_sha": commit_sha,
                "passed": passed,
                "total_matching": total,
                "returned": len(rows),
                "has_more": clamped_offset + len(rows) < total,
                "tests": rows,
            },
            task_ref=resolved_task_ref,
            entity="verified_test",
        )
