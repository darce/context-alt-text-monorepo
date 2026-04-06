from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import BaseModel, Field


class ListNextActionsOp(BaseModel):
    operation: Literal["list"]
    status: str | None = None


class UpdateNextActionsOp(BaseModel):
    operation: Literal["update"]
    action_id: int
    action: str | None = None


NextActionsPayload = Annotated[
    ListNextActionsOp | UpdateNextActionsOp,
    Field(discriminator="operation"),
]


def _build_spike_tool_schema() -> dict:
    mcp = FastMCP("schema-spike")

    def next_actions(event: NextActionsPayload) -> str:
        return event.operation

    tool = mcp.add_tool(next_actions)
    return tool.parameters


def test_fastmcp_discriminated_union_schema_uses_oneof_and_discriminator() -> None:
    schema = _build_spike_tool_schema()

    assert schema["type"] == "object"
    assert schema["required"] == ["event"]

    event = schema["properties"]["event"]
    assert event["discriminator"]["propertyName"] == "operation"
    assert event["discriminator"]["mapping"] == {
        "list": "#/$defs/ListNextActionsOp",
        "update": "#/$defs/UpdateNextActionsOp",
    }
    assert event["oneOf"] == [
        {"$ref": "#/$defs/ListNextActionsOp"},
        {"$ref": "#/$defs/UpdateNextActionsOp"},
    ]


def test_fastmcp_discriminated_union_schema_preserves_variant_requirements() -> None:
    schema = _build_spike_tool_schema()

    list_op = schema["$defs"]["ListNextActionsOp"]
    update_op = schema["$defs"]["UpdateNextActionsOp"]

    assert list_op["required"] == ["operation"]
    assert list_op["properties"]["operation"]["const"] == "list"
    assert update_op["required"] == ["operation", "action_id"]
    assert update_op["properties"]["operation"]["const"] == "update"
    assert update_op["properties"]["action_id"]["type"] == "integer"
