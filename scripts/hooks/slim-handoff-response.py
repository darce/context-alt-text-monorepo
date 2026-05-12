#!/usr/bin/env python3
"""PostToolUse hook: context-budget advisory for verbose handoff responses.

Fires after get_handoff_state and load_session MCP calls.  When the
response exceeds the character threshold, injects a note reminding the
model to use bounded-read levers on the *next* call.  Also records a
turn_metrics row in handoff.db so advisory frequency is observable.

This addresses the pattern found in handoff.db where heavy tasks produce
get_handoff_state responses of 15-30K chars (~4-7.5K tokens), mostly from
decision rationale bloat and fixed-finding audit fields.

Hook contract (Claude Code PostToolUse):
  stdin:  JSON with tool_response (MCP result envelope)
  stdout: JSON with hookSpecificOutput.additionalContext (or {} to no-op)
  exit 0 always (observational hook, never blocks)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Threshold: ~2K tokens.  The handoff server's own oversize_response
# advisory fires at ~20KB / ~5K tokens.  This hook fires earlier to
# steer behavior before the expensive call.
CHAR_THRESHOLD = 8_000

# Repo root is two levels up from scripts/hooks/.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _estimate_tokens(text: str) -> int:
    return len(text) // 4


def _count_sections(response_text: str) -> dict[str, int]:
    """Rough section counts from the JSON keys present."""
    counts: dict[str, int] = {}
    for key in ("decisions", "verified_tests", "findings_open",
                "findings_all", "blockers", "next_actions"):
        occurrences = response_text.count(f'"{key}"')
        if occurrences:
            counts[key] = occurrences
    return counts


def _record_advisory_metric(char_count: int, token_est: int, sections: dict[str, int]) -> None:
    """Best-effort: write advisory event to turn_metrics in handoff.db."""
    try:
        from agent_handoff_mcp import RuntimeConfig, configure_runtime
        from agent_orchestrator_mcp.lanes import PromptMetrics, record_turn_metric
        configure_runtime(RuntimeConfig.for_repo(_REPO_ROOT))
        record_turn_metric(
            session="slim_handoff_advisory",
            phase="handoff_read_advisory",
            backend="slim_handoff_hook",
            prompt_metrics=PromptMetrics(
                prompt_chars=char_count,
                prompt_tokens=token_est,
                pressure_level="high",
                prompt_token_source="char_estimate",
            ),
            section_sizes=sections if sections else None,
        )
    except Exception:
        pass  # never block the hook's primary advisory output


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        print("{}")
        return

    response = payload.get("tool_response") or payload.get("tool_output") or {}
    if isinstance(response, str):
        response_text = response
    elif isinstance(response, dict):
        response_text = json.dumps(response)
    else:
        print("{}")
        return

    char_count = len(response_text)
    if char_count < CHAR_THRESHOLD:
        print("{}")
        return

    token_est = _estimate_tokens(response_text)
    sections = _count_sections(response_text)

    _record_advisory_metric(char_count, token_est, sections)

    lines = [
        f"Handoff response: ~{char_count:,} chars (~{token_est:,} tokens).",
        "Reduce context usage on the next call with bounded-read levers:",
        '  sections="identity" -- routine identity-only checks',
        '  detail="summary"   -- truncate rationale/fix/evidence to 200 chars',
        "  top_n_decisions=1  -- fewer historical decisions",
    ]

    if sections:
        section_parts = [f"{k}={v}" for k, v in sections.items() if v > 1]
        if section_parts:
            lines.append(f"  Sections present: {', '.join(section_parts)}")

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "\n".join(lines),
        }
    }))


if __name__ == "__main__":
    main()
