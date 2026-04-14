from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastmcp.client import Client, PythonStdioTransport

# Tool families that must always be present on the consolidated 19-tool surface.
_CORE_TOOLS = {
    "get_handoff_state",
    "set_handoff_state",
    "record_event",
    "next_actions",
    "review_findings",
    "review_runs",
    "handoff_close_check",
    "generate_current_task_md",
    "load_session",
    "close_slice",
}

# Legacy extended-only tools from the old split; now always present too.
_EXTENDED_ONLY_TOOLS = {
    "audit_decision_ids",
    "export_handoff_state",
    "import_handoff_state",
    "archive_task_state",
    "get_verified_tests",
    "update_task_status",
    "artifacts",
    "search_handoff",
}


def test_stdio_server_lists_handoff_tools(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> list[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return sorted(tool.name for tool in tools)

    tool_names = asyncio.run(_run())
    # Default launch now exposes the single 19-tool consolidated surface.
    assert "get_handoff_state" in tool_names
    assert "record_event" in tool_names
    assert "review_findings" in tool_names
    assert "review_runs" in tool_names
    assert "handoff_close_check" in tool_names
    assert "load_session" in tool_names
    assert "close_slice" in tool_names
    assert "record_decision" not in tool_names
    # orchestration tools moved to agent-orchestrator-mcp
    assert "record_lane_brief" not in tool_names
    assert "orchestrator_start" not in tool_names
    assert "worker_start" not in tool_names
    assert "run_structured_turn" not in tool_names


def test_stdio_legacy_core_profile_still_exposes_all_20_tools(tmp_path: Path) -> None:
    """Legacy --tool-profile core is accepted but now exposes the full 20-tool surface."""
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> set[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "--tool-profile", "core", "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "core-profile-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    tool_names = asyncio.run(_run())
    missing_core = _CORE_TOOLS - tool_names
    assert not missing_core, f"Core tools missing from legacy core launch: {missing_core}"
    missing_extended = _EXTENDED_ONLY_TOOLS - tool_names
    assert not missing_extended, f"Legacy extended tools missing from unified launch: {missing_extended}"
    assert len(tool_names) == 20


def test_stdio_extended_profile_exposes_all_20_tools(tmp_path: Path) -> None:
    """Legacy --tool-profile extended still exposes the unified 20-tool surface."""
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> set[str]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "--tool-profile", "extended", "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "extended-profile-smoke.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools}

    tool_names = asyncio.run(_run())
    assert _CORE_TOOLS <= tool_names, f"Core tools missing from extended profile: {_CORE_TOOLS - tool_names}"
    assert _EXTENDED_ONLY_TOOLS <= tool_names, (
        f"Extended tools missing from extended profile: {_EXTENDED_ONLY_TOOLS - tool_names}"
    )
    assert len(tool_names) == 20


def _collect_schema_types(schema: dict[str, Any], root_schema: dict[str, Any]) -> set[str]:
    collected: set[str] = set()
    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        collected.add(schema_type)
    elif isinstance(schema_type, list):
        collected.update(item for item in schema_type if isinstance(item, str))
    for key in ("anyOf", "oneOf", "allOf"):
        for entry in schema.get(key, []):
            if isinstance(entry, dict):
                collected.update(_collect_schema_types(entry, root_schema))
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        def_name = ref.split("/", 2)[-1]
        target = root_schema.get("$defs", {}).get(def_name)
        if isinstance(target, dict):
            collected.update(_collect_schema_types(target, root_schema))
    return collected


def _resolve_schema_object(schema: dict[str, Any], root_schema: dict[str, Any]) -> dict[str, Any] | None:
    schema_type = schema.get("type")
    if schema_type == "object":
        return schema
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/$defs/"):
        def_name = ref.split("/", 2)[-1]
        target = root_schema.get("$defs", {}).get(def_name)
        if isinstance(target, dict):
            return _resolve_schema_object(target, root_schema)
    for key in ("anyOf", "oneOf", "allOf"):
        for entry in schema.get(key, []):
            if isinstance(entry, dict):
                resolved = _resolve_schema_object(entry, root_schema)
                if resolved is not None:
                    return resolved
    return None


def test_stdio_next_actions_schema_exposes_discriminated_variants(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> dict[str, Any]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-schema-next-actions.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == "next_actions")
            return tool.inputSchema

    schema = asyncio.run(_run())
    assert schema["required"] == ["action"]

    action_schema = schema["properties"]["action"]
    assert len(action_schema["oneOf"]) == 5
    action_variants = {
        variant["properties"]["operation"]["const"]: variant
        for variant in action_schema["oneOf"]
        if "properties" in variant and "operation" in variant["properties"]
    }
    assert set(action_variants) == {"list", "add", "update", "complete", "skip"}

    update_schema = action_variants["update"]
    assert set(update_schema["required"]) == {"operation", "action_id"}
    action_id_types = _collect_schema_types(update_schema["properties"]["action_id"], schema)
    assert action_id_types == {"integer"}
    priority_types = _collect_schema_types(update_schema["properties"]["priority"], schema)
    assert {"integer", "null"} <= priority_types

    status_property = update_schema["properties"]["status"]
    assert set(status_property["anyOf"][0]["enum"]) == {"pending", "done", "skipped"}
    assert "Only used for update operations" in status_property["description"]

    add_schema = action_variants["add"]
    actor_types = _collect_schema_types(add_schema["properties"]["actor"], schema)
    assert {"object", "null"} <= actor_types
    actor_object = _resolve_schema_object(add_schema["properties"]["actor"], schema)
    assert actor_object is not None
    assert {"agent", "model", "model_label", "reasoning_level", "branch", "commit_sha", "lane_id"} <= set(
        actor_object["properties"].keys()
    )
    assert "structured provenance override" in add_schema["properties"]["actor"]["description"]


def test_stdio_tool_responses_return_native_dict_not_wrapped_string(tmp_path: Path) -> None:
    """Regression test for AHMCP-7 double-serialization fix.

    Tool handlers in core.py / decisions.py / handoff_state.py / review_findings.py
    return JSON strings via _envelope() / _json_response() (so the orchestrator's
    string-based protocol can still consume them). build_handoff_mcp() wraps
    these handlers in a json.loads() shim so FastMCP receives dicts and the
    MCP wire format carries native nested structures.

    Two regressions have been seen here historically:

    1. The wrapper conditional used `handler.__annotations__.get("return") is str`,
       but `api.py` uses `from __future__ import annotations` (PEP 563) which
       stores all annotations as strings. So the conditional `'str' is str`
       was always False, and the wrapper was never applied. Tools shipped with
       the original `-> str` return annotation, FastMCP marked them with
       `x-fastmcp-wrap-result: True` in function_parsing.py:213-218, and tool.py's
       convert_result() returned `structured_content={"result": <stringified JSON>}`.

    2. Even when the wrapper was applied, it had a `*args/**kwargs` signature.
       FastMCP rejects those in function_parsing.py:100-107. The wrapper now
       sets `__signature__` explicitly to the original's parameters with
       `return_annotation=dict`, satisfying all FastMCP checks.

    A correct response has the native envelope shape:
        {"ok": true, "data": {...}, "scope": {...}, "tool": "..."}

    A double-serialized response is:
        structured_content = {"result": "{\\"ok\\": true, \\"data\\": ...}"}

    The MCP client deserializes structured_content into the call result; this
    test asserts the structured shape directly, so a regression that wraps the
    payload in {"result": "..."} fails immediately.
    """
    import json as _json

    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> tuple[dict[str, Any], dict[str, Any] | None]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-dict-response.log",
        )
        async with Client(transport) as client:
            result = await client.call_tool("get_handoff_state", {"sections": "identity"})
            text_payload = _json.loads(result.content[0].text)
            structured = result.structured_content
            return text_payload, structured

    text_payload, structured = asyncio.run(_run())

    # Primary assertion: structured_content must be the native envelope, not
    # `{"result": "<escaped JSON string>"}`. This is the path FastMCP wraps
    # when it sees a non-object return type.
    assert structured is not None, "Expected structured_content from FastMCP, got None"
    assert not (list(structured.keys()) == ["result"] and isinstance(structured["result"], str)), (
        "Double-serialization regression: structured_content is "
        f"{{'result': '<escaped JSON>'}} instead of a native dict. "
        f"Got: {structured!r}"
    )
    assert "ok" in structured, f"structured_content missing 'ok' key — expected native envelope, got: {structured!r}"
    assert "tool" in structured, (
        f"structured_content missing 'tool' key — expected native envelope, got: {structured!r}"
    )
    assert structured["tool"] == "get_handoff_state"
    assert structured["ok"] is True
    assert "data" in structured

    # Secondary assertion: text content payload should also be the native envelope.
    assert "ok" in text_payload
    assert text_payload["tool"] == "get_handoff_state"


def test_stdio_record_event_schema_exposes_discriminated_variants(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> dict[str, Any]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-schema-record-event.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == "record_event")
            return tool.inputSchema

    schema = asyncio.run(_run())
    assert schema["required"] == ["event"]

    event_schema = schema["properties"]["event"]
    # FastMCP 3.x may strip the Pydantic/OpenAPI discriminator key from the
    # MCP JSON Schema, but the oneOf variants and their event_kind const
    # fields must still be present for agent discovery.
    if "discriminator" in event_schema:
        assert event_schema["discriminator"]["propertyName"] == "event_kind"
    assert len(event_schema["oneOf"]) == 3

    event_variants = {
        variant["properties"]["event_kind"]["const"]: variant
        for variant in event_schema["oneOf"]
        if "properties" in variant and "event_kind" in variant["properties"]
    }
    assert set(event_variants) == {"decision", "test_result", "blocker"}

    decision_schema = event_variants["decision"]
    assert set(decision_schema["required"]) == {"event_kind", "session", "decision"}
    changed_files_types = _collect_schema_types(decision_schema["properties"]["changed_files"], schema)
    assert {"array", "null"} <= changed_files_types
    assert "monorepo-relative paths" in decision_schema["properties"]["changed_files"]["description"]

    actor_types = _collect_schema_types(decision_schema["properties"]["actor"], schema)
    assert {"object", "null"} <= actor_types
    actor_object = _resolve_schema_object(decision_schema["properties"]["actor"], schema)
    assert actor_object is not None
    assert "Canonical human-readable label" in actor_object["properties"]["model_label"]["description"]
