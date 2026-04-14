from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_PATH = REPO_ROOT / "packages" / "codex-subagent-bridge" / "src" / "codex_subagent_bridge.py"
LANE_EXEC_PATH = REPO_ROOT / "scripts" / "mcp" / "lane_exec.py"
REVIEW_RUNNER_PATH = REPO_ROOT / "scripts" / "mcp" / "review_runner.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStdin:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, data: str) -> int:
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeStdout:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._lines = [json.dumps(message) + "\n" for message in messages]

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0)
        return ""

    def close(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self.pid = 999
        self.returncode = 0
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(messages)
        self.stderr = _FakeStdout([])

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def kill(self) -> None:
        self.returncode = -9


def _run_bridge(payload: dict[str, Any]) -> dict[str, Any]:
    bridge = _load_module("codex_subagent_bridge", BRIDGE_PATH)
    fake_proc = _FakeProcess(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"},
            },
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "item/completed",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "item": {"structuredContent": payload}},
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
            },
        ]
    )
    client = bridge.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    try:
        client.initialize()
        thread_id = client.start_thread()
        return client.run_structured_turn(thread_id=thread_id, prompt="Solve it", output_schema={"type": "object"})
    finally:
        client.close()


def test_bridge_payload_satisfies_lane_exec_contract() -> None:
    lane_exec = _load_module("lane_exec", LANE_EXEC_PATH)
    payload = _run_bridge(
        {
            "handoff_action": "merge_ready",
            "summary": "Implemented the lane.",
            "details": "The bridge completed the structured worker turn.",
            "tests_run": ["pytest -q packages/codex-subagent-bridge/tests"],
            "blockers": [],
        }
    )
    assert lane_exec._validate_lane_result_payload(payload) == payload


def test_bridge_payload_satisfies_review_runner_contract() -> None:
    review_runner = _load_module("review_runner", REVIEW_RUNNER_PATH)
    payload = _run_bridge(
        {
            "findings": [
                {
                    "severity": "low",
                    "category": "GAP",
                    "file_path": "scripts/mcp/lane_exec.py",
                    "description": "Example finding.",
                }
            ],
            "summary": "One low finding.",
        }
    )
    assert review_runner._validate_review_result(payload) == payload
