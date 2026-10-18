"""Unit tests for CheckResult defaults."""

from __future__ import annotations

from recognition.application.assignment.checks.base import CheckResult


def test_check_result_defaults() -> None:
    """CheckResult should default to non-fatal suggestion-style failure."""
    result = CheckResult(passed=False)
    assert result.passed is False
    assert result.is_fatal is False
    assert result.should_reject is False
    assert result.reason is None
    assert result.metadata is None


def test_check_result_optional_metadata() -> None:
    """Metadata and reason should be captured when provided."""
    result = CheckResult(
        passed=True,
        is_fatal=True,
        should_reject=True,
        reason="too dissimilar",
        metadata={"min_similarity": 0.5},
    )

    assert result.passed is True
    assert result.is_fatal is True
    assert result.should_reject is True
    assert result.reason == "too dissimilar"
    assert result.metadata == {"min_similarity": 0.5}
