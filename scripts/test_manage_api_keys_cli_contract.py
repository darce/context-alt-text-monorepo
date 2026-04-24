"""Docs-integrity guard for E15-3a Slice 3 CLI invocations.

`scripts/manage_api_keys.py` now requires a `--env {prod,dev,local}` flag
(E15-3a-BR-02). The Slice 3 task plan and run log command operators to
provision a throwaway production key via this CLI; those instructions must
include `--env prod` or the operator's first run fails closed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TASK_PLAN = REPO_ROOT / "docs" / "tasks" / "15.0" / "E15-3a-localwp-oci-roundtrip-task-plan.md"
RUN_LOG = REPO_ROOT / "docs" / "tasks" / "15.0" / "E15-3a-localwp-oci-run-log.md"

MANAGE_KEYS_LINE = re.compile(r"python -m scripts\.manage_api_keys\s+(?P<tail>[^\n`]+)")


def _each_manage_keys_invocation(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [m.group(0) for m in MANAGE_KEYS_LINE.finditer(text)]


def test_task_plan_includes_env_prod_on_every_manage_api_keys_call() -> None:
    invocations = _each_manage_keys_invocation(TASK_PLAN)
    assert invocations, "expected at least one manage_api_keys invocation in the task plan"
    for cmd in invocations:
        assert "--env prod" in cmd, f"task plan invocation missing --env prod: {cmd}"


def test_run_log_includes_env_prod_on_every_manage_api_keys_call() -> None:
    invocations = _each_manage_keys_invocation(RUN_LOG)
    assert invocations, "expected at least one manage_api_keys invocation in the run log"
    for cmd in invocations:
        assert "--env prod" in cmd, f"run log invocation missing --env prod: {cmd}"
