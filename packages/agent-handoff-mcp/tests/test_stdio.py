from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastmcp.client import Client, PythonStdioTransport

# Core profile tools that must always be present in the default (core) launch.
_CORE_TOOLS = {
    "get_handoff_state",
    "set_handoff_state",
    "record_decision",
    "update_next_actions",
    "record_test_result",
    "report_blocker",
    "record_review_finding",
    "batch_record_review_findings",
    "update_review_finding",
    "list_review_findings",
    "record_review_run",
    "list_review_runs",
    "handoff_close_check",
    "generate_current_task_md",
    "load_session",
    "close_slice",
}

# Extended tools that must NOT appear in the default (core) profile.
_EXTENDED_ONLY_TOOLS = {
    "list_next_actions",
    "get_review_coverage",
    "audit_decision_ids",
    "export_handoff_state",
    "import_handoff_state",
    "archive_task_state",
    "update_task_status",
    "record_artifact",
    "search_artifacts",
    "get_artifact",
    "purge_artifacts",
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
    # Default launch uses extended profile — all tools present.
    assert "get_handoff_state" in tool_names
    assert "record_review_finding" in tool_names
    assert "handoff_close_check" in tool_names
    assert "load_session" in tool_names
    assert "close_slice" in tool_names
    # orchestration tools moved to agent-orchestrator-mcp
    assert "record_lane_brief" not in tool_names
    assert "orchestrator_start" not in tool_names
    assert "worker_start" not in tool_names
    assert "run_structured_turn" not in tool_names


def test_stdio_core_profile_excludes_extended_tools(tmp_path: Path) -> None:
    """Explicit --tool-profile core must include all 16 core tools and exclude all 11 extended."""
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
    assert not missing_core, f"Core tools missing from core profile: {missing_core}"
    present_extended = _EXTENDED_ONLY_TOOLS & tool_names
    assert not present_extended, f"Extended tools incorrectly present in core profile: {present_extended}"
    assert len(tool_names) == 16


def test_stdio_extended_profile_exposes_all_27_tools(tmp_path: Path) -> None:
    """--tool-profile extended must expose all 27 tools."""
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
    assert len(tool_names) == 28


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


def test_stdio_update_next_actions_schema_is_agent_discoverable(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> dict[str, Any]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-schema-update-next-actions.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == "update_next_actions")
            return tool.inputSchema

    schema = asyncio.run(_run())
    properties = schema["properties"]

    assert schema["type"] == "object"
    assert schema["required"] == ["operation"]
    assert properties["operation"]["enum"] == ["add", "update", "complete", "skip"]
    assert "Mutation to apply" in properties["operation"]["description"]

    action_id_types = _collect_schema_types(properties["action_id"], schema)
    assert {"integer", "null"} <= action_id_types
    priority_types = _collect_schema_types(properties["priority"], schema)
    assert {"integer", "null"} <= priority_types

    status_property = properties["status"]
    assert set(status_property["anyOf"][0]["enum"]) == {"pending", "done", "skipped"}
    assert "Only used for update operations" in status_property["description"]

    actor_types = _collect_schema_types(properties["actor"], schema)
    assert {"object", "null"} <= actor_types
    actor_object = _resolve_schema_object(properties["actor"], schema)
    assert actor_object is not None
    assert {"agent", "model", "model_label", "reasoning_level", "branch", "commit_sha", "lane_id"} <= set(
        actor_object["properties"].keys()
    )
    assert "structured provenance override" in properties["actor"]["description"]


def test_stdio_record_decision_schema_exposes_changed_files_and_actor(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    launcher = (repo_root / "packages" / "agent-handoff-mcp" / "src" / "agent_handoff_mcp_launcher.py").resolve()

    async def _run() -> dict[str, Any]:
        transport = PythonStdioTransport(
            script_path=launcher,
            args=["--workspace-root", str(repo_root), "serve-stdio"],
            cwd=str(repo_root),
            log_file=tmp_path / "stdio-schema-record-decision.log",
        )
        async with Client(transport) as client:
            tools = await client.list_tools()
            tool = next(tool for tool in tools if tool.name == "record_decision")
            return tool.inputSchema

    schema = asyncio.run(_run())
    properties = schema["properties"]

    assert set(schema["required"]) == {"session", "decision"}
    changed_files_types = _collect_schema_types(properties["changed_files"], schema)
    assert {"array", "null"} <= changed_files_types
    assert "monorepo-relative paths" in properties["changed_files"]["description"]

    actor_types = _collect_schema_types(properties["actor"], schema)
    assert {"object", "null"} <= actor_types
    actor_object = _resolve_schema_object(properties["actor"], schema)
    assert actor_object is not None
    assert "Canonical human-readable label" in actor_object["properties"]["model_label"]["description"]
