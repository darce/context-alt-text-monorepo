from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "packages" / "codex-subagent-bridge" / "src" / "codex_subagent_bridge.py"
FIXTURE_PATH = (
    REPO_ROOT
    / "packages"
    / "codex-subagent-bridge"
    / "tests"
    / "fixtures"
    / "codex_app_server_protocol.v2.schemas.json"
)


def _load_bridge_module():
    spec = importlib.util.spec_from_file_location("codex_subagent_bridge", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load bridge module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FakeStdin:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.closed = False

    def write(self, data: str) -> int:
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _FakeStdout:
    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.closed = False

    def readline(self) -> str:
        if self._lines:
            return self._lines.pop(0)
        return ""

    def close(self) -> None:
        self.closed = True


class _FakeStderr:
    def __init__(self, text: str = "") -> None:
        self._text = text
        self.closed = False

    def read(self) -> str:
        return self._text

    def close(self) -> None:
        self.closed = True


class _FakeProcess:
    def __init__(self, messages: list[dict[str, Any]], *, stderr_text: str = "", returncode: int | None = 0) -> None:
        self.pid = 4321
        self.returncode = returncode
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout([json.dumps(message) + "\n" for message in messages])
        self.stderr = _FakeStderr(stderr_text)
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        if self.returncode is None:
            self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


def test_protocol_fixture_mentions_structured_turn_methods() -> None:
    data = json.loads(FIXTURE_PATH.read_text())
    serialized = json.dumps(data)
    assert "thread/start" in serialized
    assert "turn/start" in serialized
    assert "turn/completed" in serialized
    assert "outputSchema" in serialized


def test_run_subagent_drives_protocol_and_returns_structured_payload() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "method": "thread/started", "params": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "method": "turn/started", "params": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {"type": "assistant_message", "structuredContent": {"summary": "done", "ok": True}},
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
            },
        ]
    )

    client = mod.AppServerClient(
        cwd="/tmp/worktree",
        env={"CODEX_REASONING_EFFORT": "high", "PYENV_VERSION": "description-service"},
        popen_factory=lambda *args, **kwargs: fake_proc,
    )
    client.start()
    try:
        client.initialize()
        thread_id = client.start_thread()
        result = client.run_structured_turn(
            thread_id=thread_id,
            prompt="Solve the task.",
            output_schema={"type": "object"},
        )
    finally:
        client.close()

    assert result == {"summary": "done", "ok": True}
    requests = [json.loads(line) for line in fake_proc.stdin.lines]
    assert [request["method"] for request in requests] == ["initialize", "thread/start", "turn/start"]
    assert requests[1]["params"]["cwd"] == "/tmp/worktree"
    assert requests[1]["params"]["approvalPolicy"] == "never"
    assert requests[2]["params"]["input"] == [{"type": "text", "text": "Solve the task."}]
    assert requests[2]["params"]["outputSchema"] == {"type": "object"}
    assert requests[2]["params"]["effort"] == "high"
    assert fake_proc.stdin.closed is True


def test_run_subagent_accepts_agent_message_text_json_payload() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "item/completed",
                "params": {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "item": {
                        "type": "agentMessage",
                        "id": "msg-1",
                        "text": "{\"ok\":true,\"summary\":\"bridge live test passed\"}",
                        "phase": "final_answer",
                    },
                },
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
            },
        ]
    )
    client = mod.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    try:
        client.initialize()
        thread_id = client.start_thread()
        result = client.run_structured_turn(
            thread_id=thread_id,
            prompt="Solve the task.",
            output_schema={"type": "object"},
        )
    finally:
        client.close()

    assert result == {"ok": True, "summary": "bridge live test passed"}


def test_run_subagent_public_entrypoint_launches_client_and_merges_env() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "item/completed",
                "params": {"threadId": "thread-1", "turnId": "turn-1", "item": {"structuredContent": {"ok": True}}},
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
            },
        ]
    )
    captured: dict[str, Any] = {}

    def _fake_popen(*args: Any, **kwargs: Any) -> _FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_proc

    original_client = mod.AppServerClient

    class _PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["popen_factory"] = _fake_popen
            super().__init__(*args, **kwargs)

    mod.AppServerClient = _PatchedClient
    try:
        result = mod.run_subagent(
            prompt="Solve the task.",
            schema={"type": "object"},
            cwd="/tmp/worktree",
            env={"TMPDIR": "/tmp/bridge", "PYENV_VERSION": "description-service"},
        )
    finally:
        mod.AppServerClient = original_client

    assert result == {"ok": True}
    assert captured["args"][0] == ["codex", "app-server", "--listen", "stdio://"]
    assert captured["kwargs"]["cwd"] == "/tmp/worktree"
    assert captured["kwargs"]["env"]["TMPDIR"] == "/tmp/bridge"
    assert captured["kwargs"]["env"]["PYENV_VERSION"] == "description-service"
    assert captured["kwargs"]["env"]["PATH"] == os.environ["PATH"]


def test_run_structured_turn_fails_when_no_structured_payload_arrives() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
            },
        ]
    )
    client = mod.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    try:
        client.initialize()
        thread_id = client.start_thread()
        with pytest.raises(RuntimeError, match="without emitting structured output"):
            client.run_structured_turn(thread_id=thread_id, prompt="Solve the task.", output_schema={"type": "object"})
    finally:
        client.close()


def test_invalid_json_from_app_server_raises_runtime_error_and_closes_process() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess([], stderr_text="bad output", returncode=1)
    fake_proc.stdout = _FakeStdout(["not-json\n"])

    client = mod.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    with pytest.raises(RuntimeError, match="invalid JSON"):
        client.initialize()
    client.close()
    assert fake_proc.stdin.closed is True
    assert fake_proc.stdout.closed is True
    assert fake_proc.stderr.closed is True


def test_failed_turn_raises_runtime_error_with_turn_message() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {
                    "threadId": "thread-1",
                    "turn": {
                        "id": "turn-1",
                        "status": "failed",
                        "items": [],
                        "error": {"message": "approval required"},
                    },
                },
            },
        ]
    )
    client = mod.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    try:
        client.initialize()
        thread_id = client.start_thread()
        with pytest.raises(RuntimeError, match="approval required"):
            client.run_structured_turn(thread_id=thread_id, prompt="Solve the task.", output_schema={"type": "object"})
    finally:
        client.close()


def test_stream_timeout_raises_clear_runtime_error() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess([], returncode=None)
    client = mod.AppServerClient(
        cwd="/tmp/worktree",
        timeout_seconds=0.0,
        popen_factory=lambda *args, **kwargs: fake_proc,
    )
    client.start()
    with pytest.raises(RuntimeError, match="Timed out waiting for codex app-server output"):
        client._read_message(deadline=0.0)
    client.close()


def test_close_terminates_long_running_process() -> None:
    mod = _load_bridge_module()
    fake_proc = _FakeProcess([], returncode=None)
    client = mod.AppServerClient(cwd="/tmp/worktree", popen_factory=lambda *args, **kwargs: fake_proc)
    client.start()
    client.close()
    assert fake_proc.terminated is True
    assert fake_proc.killed is False


def test_invalid_reasoning_effort_fails_loudly() -> None:
    mod = _load_bridge_module()
    with pytest.raises(RuntimeError, match="Unsupported reasoning effort"):
        mod._normalize_reasoning_effort("extreme")


def test_shared_session_mode_reuses_initialized_client_for_multiple_calls() -> None:
    mod = _load_bridge_module()
    procs = [
        _FakeProcess(
            [
                {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
                {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
                {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {"threadId": "thread-1", "turnId": "turn-1", "item": {"structuredContent": {"run": 1}}},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed", "items": []}},
                },
                {"jsonrpc": "2.0", "id": 4, "result": {"thread": {"id": "thread-2"}}},
                {"jsonrpc": "2.0", "id": 5, "result": {"turn": {"id": "turn-2", "status": "inProgress"}}},
                {
                    "jsonrpc": "2.0",
                    "method": "item/completed",
                    "params": {"threadId": "thread-2", "turnId": "turn-2", "item": {"structuredContent": {"run": 2}}},
                },
                {
                    "jsonrpc": "2.0",
                    "method": "turn/completed",
                    "params": {"threadId": "thread-2", "turn": {"id": "turn-2", "status": "completed", "items": []}},
                },
            ]
        )
    ]
    popen_calls: list[tuple[Any, Any]] = []

    def _fake_popen(*args: Any, **kwargs: Any) -> _FakeProcess:
        popen_calls.append((args, kwargs))
        return procs[0]

    original_client = mod.AppServerClient
    original_close = mod.close_shared_clients

    class _PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["popen_factory"] = _fake_popen
            super().__init__(*args, **kwargs)

    mod.AppServerClient = _PatchedClient
    try:
        result_one = mod.run_subagent(
            prompt="Solve one",
            schema={"type": "object"},
            cwd="/tmp/worktree",
            env={"CODEX_SUBAGENT_BRIDGE_SESSION_MODE": "shared"},
        )
        result_two = mod.run_subagent(
            prompt="Solve two",
            schema={"type": "object"},
            cwd="/tmp/worktree",
            env={"CODEX_SUBAGENT_BRIDGE_SESSION_MODE": "shared"},
        )
    finally:
        mod.close_shared_clients()
        mod.AppServerClient = original_client

    assert result_one == {"run": 1}
    assert result_two == {"run": 2}
    assert len(popen_calls) == 1
    requests = [json.loads(line) for line in procs[0].stdin.lines]
    assert [request["method"] for request in requests] == [
        "initialize",
        "thread/start",
        "turn/start",
        "thread/start",
        "turn/start",
    ]


def test_shared_session_failure_discards_cached_client() -> None:
    mod = _load_bridge_module()
    first_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-1"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-1", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "failed", "items": [], "error": {"message": "boom"}}},
            },
        ],
        returncode=None,
    )
    second_proc = _FakeProcess(
        [
            {"jsonrpc": "2.0", "id": 1, "result": {"userAgent": "codex", "platformOs": "macos", "platformFamily": "unix"}},
            {"jsonrpc": "2.0", "id": 2, "result": {"thread": {"id": "thread-2"}}},
            {"jsonrpc": "2.0", "id": 3, "result": {"turn": {"id": "turn-2", "status": "inProgress"}}},
            {
                "jsonrpc": "2.0",
                "method": "item/completed",
                "params": {"threadId": "thread-2", "turnId": "turn-2", "item": {"structuredContent": {"ok": True}}},
            },
            {
                "jsonrpc": "2.0",
                "method": "turn/completed",
                "params": {"threadId": "thread-2", "turn": {"id": "turn-2", "status": "completed", "items": []}},
            },
        ],
        returncode=None,
    )
    fake_procs = [first_proc, second_proc]

    def _fake_popen(*args: Any, **kwargs: Any) -> _FakeProcess:
        return fake_procs.pop(0)

    original_client = mod.AppServerClient

    class _PatchedClient(original_client):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["popen_factory"] = _fake_popen
            super().__init__(*args, **kwargs)

    mod.AppServerClient = _PatchedClient
    try:
        with pytest.raises(RuntimeError, match="boom"):
            mod.run_subagent(
                prompt="Fail",
                schema={"type": "object"},
                cwd="/tmp/worktree",
                env={"CODEX_SUBAGENT_BRIDGE_SESSION_MODE": "shared"},
            )

        result = mod.run_subagent(
            prompt="Recover",
            schema={"type": "object"},
            cwd="/tmp/worktree",
            env={"CODEX_SUBAGENT_BRIDGE_SESSION_MODE": "shared"},
        )
    finally:
        mod.close_shared_clients()
        mod.AppServerClient = original_client

    assert first_proc.terminated is True
    assert result == {"ok": True}
