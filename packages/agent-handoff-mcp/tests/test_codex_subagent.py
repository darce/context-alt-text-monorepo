from __future__ import annotations

from pathlib import Path

from agent_handoff_mcp.orchestration.adapters.codex_subagent import CodexSubagentAdapter


def test_codex_subagent_adapter_normalizes_flat_usage_payload() -> None:
    adapter = CodexSubagentAdapter(
        runner=lambda **_: {
            "handoff_action": "merge_ready",
            "summary": "done",
            "details": "details",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "cached_tokens": 8,
                "reasoning_tokens": 5,
                "total_tokens": 150,
            },
        },
        name="codex-subagent",
    )

    result = adapter.execute(
        prompt="hello",
        schema={},
        worktree_path=Path("/tmp"),
        model="gpt-5.4",
        reasoning_effort="high",
    )

    assert result.token_usage is not None
    assert result.token_usage["usage_source"] == "observed"
    assert result.token_usage["last"]["input_tokens"] == 120
    assert result.token_usage["last"]["output_tokens"] == 30
    assert result.token_usage["last"]["cached_input_tokens"] == 8
    assert result.token_usage["last"]["reasoning_output_tokens"] == 5
    assert result.response_model == "gpt-5.4"
    assert result.reasoning_effort == "high"
