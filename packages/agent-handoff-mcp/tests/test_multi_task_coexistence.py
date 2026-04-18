"""Regression tests for E17-11 Slice 2f.

Greenfield contract: ``set_handoff_state`` and ``_set_import_active_state``
must INSERT ``handoff_state`` rows with ``id = NULL``. There is no singleton
``id = 1`` sentinel — multiple rows coexist, one per ``task_ref``. No row
evicts another on create, and ``expected_revision`` updates on task A never
touch task B.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from agent_handoff_mcp import (
    RuntimeConfig,
    configure_runtime,
    set_handoff_state,
)


def _configured_conn(tmp_path: Path) -> sqlite3.Connection:
    configure_runtime(RuntimeConfig.for_repo(tmp_path))
    from agent_handoff_mcp.shared_schema import _get_db_connection

    return _get_db_connection().__enter__()


def test_two_tasks_coexist_with_null_id(tmp_path: Path) -> None:
    """Back-to-back ``set_handoff_state`` calls produce two rows, both id=NULL."""
    conn = _configured_conn(tmp_path)
    try:
        r1 = set_handoff_state(task_ref="T1", objective="obj-1")
        assert r1["ok"] is True, r1
        r2 = set_handoff_state(task_ref="T2", objective="obj-2")
        assert r2["ok"] is True, r2

        rows = conn.execute("SELECT task_ref, id FROM handoff_state ORDER BY task_ref").fetchall()
        assert [r["task_ref"] for r in rows] == ["T1", "T2"]
        assert [r["id"] for r in rows] == [None, None], "Both rows must have id = NULL; no sentinel singleton."
    finally:
        conn.close()


def test_update_on_task_a_does_not_touch_task_b(tmp_path: Path) -> None:
    """Revision bump on task A leaves task B's revision and id untouched."""
    conn = _configured_conn(tmp_path)
    try:
        set_handoff_state(task_ref="T1", objective="obj-1")
        set_handoff_state(task_ref="T2", objective="obj-2")

        set_handoff_state(
            task_ref="T1",
            objective="obj-1-updated",
            expected_revision=0,
        )

        rows = {
            r["task_ref"]: (r["id"], int(r["revision"]), str(r["objective"]))
            for r in conn.execute("SELECT task_ref, id, revision, objective FROM handoff_state").fetchall()
        }
        assert rows["T1"] == (None, 1, "obj-1-updated")
        assert rows["T2"] == (None, 0, "obj-2"), "Task B untouched by task A update."
    finally:
        conn.close()
