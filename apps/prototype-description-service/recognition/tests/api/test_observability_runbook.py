"""Slice 3b: docs/operations/observability-runbook.md exists and covers the
operator workflows promised by Slice 3.

A structural test keeps the runbook honest: if someone renames a section or
drops the PromQL formula, the pre-merge gate catches it. This is the test
gate for a docs slice — it is not a substitute for the runbook being
useful, just proof the documented workflows are still present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
RUNBOOK = REPO_ROOT / "docs" / "operations" / "observability-runbook.md"


@pytest.fixture(scope="module")
def runbook_text() -> str:
    assert RUNBOOK.is_file(), f"runbook missing at {RUNBOOK}"
    return RUNBOOK.read_text(encoding="utf-8")


def test_runbook_exists_at_canonical_path() -> None:
    """Operators must find the runbook at a stable path so links don't rot."""
    assert RUNBOOK.is_file(), f"expected runbook at {RUNBOOK}"


@pytest.mark.parametrize(
    "heading",
    [
        "# Observability Runbook",
        "## Health and Readiness",
        "## Structured Logs",
        "## Request Metrics",
        "## Tracing a Request by Correlation ID",
        "## Common Failures",
    ],
)
def test_runbook_sections_present(runbook_text: str, heading: str) -> None:
    """Each documented workflow gets a stable top-level heading so operators
    can jump to the section by anchor and so links from alerting dashboards
    don't rot."""
    assert heading in runbook_text, f"missing heading: {heading}"


def test_runbook_includes_promql_histogram_quantile_formula(runbook_text: str) -> None:
    """P50/P95/P99 must be computed by PromQL, not exposed by the app. The
    runbook must spell out the `histogram_quantile(..., sum by (le) (rate(..._bucket[...])))`
    formula so operators do not reinvent it.
    """
    assert "histogram_quantile" in runbook_text
    assert "http_request_duration_seconds_bucket" in runbook_text
    # At least one quantile example (0.50, 0.95, or 0.99) must be present.
    assert any(q in runbook_text for q in ("0.50", "0.95", "0.99"))


def test_runbook_references_correlation_header_and_metrics_endpoint(runbook_text: str) -> None:
    """Both the correlation header (`X-Request-ID`) and `/metrics` must be
    named explicitly so operators can search logs and scrape metrics without
    guessing identifiers.
    """
    assert "X-Request-ID" in runbook_text
    assert "/metrics" in runbook_text
    assert "/health" in runbook_text
    assert "/ready" in runbook_text
