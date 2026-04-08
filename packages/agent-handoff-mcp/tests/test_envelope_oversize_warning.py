"""Regression tests for the AHMCP-14 envelope oversize-response advisory.

The motivating incident: a routine ``get_handoff_state`` call against
AOMCP-3 returned ~17.6k tokens because slice-complete decision rationales
dominated the payload. AHMCP-14 added a soft cap that appends an
``oversize_response: ...`` warning to ``payload["warnings"]`` whenever the
serialised response exceeds ``RESPONSE_OVERSIZE_WARN_BYTES``. The warning
is purely advisory — the response is still returned in full so callers are
not silently truncated, but the warning names the bounded-read levers
(``detail="summary"``, lower ``top_n_*``, ``sections="identity"``,
``fields=...``) so the next call can be narrowed.
"""
from __future__ import annotations

from agent_handoff_mcp.shared_primitives import RESPONSE_OVERSIZE_WARN_BYTES, _envelope


def test_small_payload_emits_no_oversize_warning() -> None:
    payload = _envelope(
        ok=True,
        tool="test_tool",
        data={"hello": "world"},
        task_ref="TEST-1",
    )
    assert "warnings" not in payload


def test_payload_below_threshold_preserves_caller_warnings() -> None:
    payload = _envelope(
        ok=True,
        tool="test_tool",
        data={"hello": "world"},
        warnings=["caller_warning_only"],
    )
    assert payload["warnings"] == ["caller_warning_only"]


def test_oversize_payload_appends_advisory_warning() -> None:
    # Build a deliberately large data block that exceeds the threshold.
    big_blob = "x" * (RESPONSE_OVERSIZE_WARN_BYTES + 5_000)
    payload = _envelope(
        ok=True,
        tool="get_handoff_state",
        data={"rationale": big_blob},
        task_ref="AOMCP-3",
    )
    warnings = payload.get("warnings", [])
    assert isinstance(warnings, list)
    matching = [w for w in warnings if isinstance(w, str) and w.startswith("oversize_response:")]
    assert len(matching) == 1, f"expected exactly one oversize warning, got: {warnings}"
    msg = matching[0]
    # Warning is actionable: names every bounded-read lever.
    assert 'detail="summary"' in msg
    assert "top_n_decisions" in msg
    assert 'sections="identity"' in msg
    assert "fields=" in msg


def test_oversize_payload_preserves_caller_warnings_and_appends_advisory() -> None:
    big_blob = "y" * (RESPONSE_OVERSIZE_WARN_BYTES + 1_000)
    payload = _envelope(
        ok=True,
        tool="get_handoff_state",
        data={"rationale": big_blob},
        warnings=["context_drift: shell on main"],
    )
    warnings = payload.get("warnings", [])
    assert isinstance(warnings, list)
    assert "context_drift: shell on main" in warnings
    assert any(w.startswith("oversize_response:") for w in warnings if isinstance(w, str))


def test_oversize_warning_does_not_truncate_data() -> None:
    """The advisory must not silently shrink the response payload."""
    big_blob = "z" * (RESPONSE_OVERSIZE_WARN_BYTES + 2_000)
    payload = _envelope(
        ok=True,
        tool="get_handoff_state",
        data={"rationale": big_blob},
    )
    assert payload["data"]["rationale"] == big_blob


def test_oversize_threshold_is_exclusive_at_boundary() -> None:
    """A payload exactly at the threshold should NOT trigger the advisory."""
    # Construct a payload whose serialised size is comfortably below the cap.
    payload = _envelope(
        ok=True,
        tool="test_tool",
        data={"small": "x" * 100},
    )
    assert "warnings" not in payload
