#!/usr/bin/env python3
"""Record the failing test gate for ``make slice-start`` via Python API fallback.

This helper eliminates shell-quoting bugs in ``mk/handoff.mk`` when
``TEST_CMD`` contains embedded quotes or spaces, such as Vitest ``-t``
filters. The make target passes values through environment variables so the
original command string lands in handoff state exactly as the operator typed it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from agent_handoff_mcp import RuntimeConfig, configure_runtime, record_event, render_handoff


def _require_ok(name: str, payload: Any) -> None:
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise RuntimeError(f"{name} returned ok=False: {payload}")


def record_slice_start(
    *,
    repo_root: Path,
    task_ref: str,
    session: str,
    test_command: str,
    result: str,
    exit_code: int,
    runtime_factory: Callable[[Path], RuntimeConfig] = RuntimeConfig.for_repo,
    configure_runtime_fn: Callable[[RuntimeConfig], Any] = configure_runtime,
    record_event_fn: Callable[..., Any] = record_event,
    render_handoff_fn: Callable[..., Any] = render_handoff,
) -> dict[str, Any]:
    configure_runtime_fn(runtime_factory(repo_root))

    event_result = record_event_fn(
        event={
            "event_kind": "test_result",
            "task_ref": task_ref,
            "session": session,
            "command": test_command,
            "passed": False,
            "result": result,
            "exit_code": exit_code,
        }
    )
    _require_ok("record_event", event_result)

    dashboard_result = render_handoff_fn(kind="dashboard")
    _require_ok("render_handoff(kind='dashboard')", dashboard_result)

    return {
        "record_event": event_result,
        "render_dashboard": dashboard_result,
    }


def main() -> int:
    try:
        repo_root = Path(os.environ["REPO_ROOT"])
        task_ref = os.environ["TASK"]
        session = os.environ["SESSION_NAME"]
        test_command = os.environ["TEST_CMD"]
        result = os.environ.get("RESULT", "Expected failing test before implementation begins.")
        exit_code = int(os.environ.get("EXIT_CODE", "1"))
        payload = record_slice_start(
            repo_root=repo_root,
            task_ref=task_ref,
            session=session,
            test_command=test_command,
            result=result,
            exit_code=exit_code,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"slice-start-inline: ERROR - {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())