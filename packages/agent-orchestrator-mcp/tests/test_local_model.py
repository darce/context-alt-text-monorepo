from __future__ import annotations

from agent_orchestrator_mcp.orchestration.adapters.local_model import _extract_openai_usage


def test_extract_openai_usage_normalizes_openai_compatible_payload() -> None:
    usage = _extract_openai_usage(
        {
            "usage": {
                "prompt_tokens": 90,
                "completion_tokens": 15,
                "cached_tokens": 4,
                "reasoning_tokens": 2,
                "total_tokens": 105,
            }
        }
    )

    assert usage is not None
    assert usage["usage_source"] == "observed"
    assert usage["last"]["input_tokens"] == 90
    assert usage["last"]["output_tokens"] == 15
    assert usage["last"]["cached_input_tokens"] == 4
    assert usage["last"]["reasoning_output_tokens"] == 2
    assert usage["total"]["total_tokens"] == 105
