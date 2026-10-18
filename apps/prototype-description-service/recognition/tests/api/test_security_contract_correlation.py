"""Keep the published security contract aligned with correlation middleware."""

from __future__ import annotations

from pathlib import Path

import pytest

from recognition.interface_adapters.http.middleware.correlation import (
    ACCESS_LOGGER_NAME,
    CORRELATION_ID_HEADER,
    CORRELATION_ID_LOG_FIELD,
    CORRELATION_ID_PLACEHOLDER,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
SECURITY_DOC = REPO_ROOT / "docs" / "workbay" / "contracts" / "security.md"

CORS_REQUEST_HEADERS = (
    "Authorization",
    "X-Api-Key",
    "X-Tenant-ID",
    "Content-Type",
    "Idempotency-Key",
)


@pytest.fixture(scope="module")
def security_text() -> str:
    assert SECURITY_DOC.is_file(), f"security contract missing at {SECURITY_DOC}"
    return SECURITY_DOC.read_text(encoding="utf-8")


def test_security_contract_exists_at_canonical_path() -> None:
    """The security contract must remain at its stable published path."""
    assert SECURITY_DOC.is_file(), f"expected security contract at {SECURITY_DOC}"


@pytest.mark.parametrize(
    "heading",
    [
        "# Recognition Service Security Configuration",
        "## Error Responses",
        "### Structured Error Format",
        "## Correlation ID (`X-ACX-Request-Id`)",
        "## Rate Limiting",
        "## CORS Origin Allowlist",
    ],
)
def test_security_contract_sections_present(security_text: str, heading: str) -> None:
    """The contract keeps stable headings for integrator navigation."""
    assert heading in security_text, f"missing heading: {heading}"


def test_security_contract_uses_shipped_correlation_identifiers(security_text: str) -> None:
    """The documented identifiers must come from the middleware source of truth."""
    for identifier in (
        CORRELATION_ID_HEADER,
        CORRELATION_ID_LOG_FIELD,
        CORRELATION_ID_PLACEHOLDER,
        ACCESS_LOGGER_NAME,
    ):
        assert identifier in security_text


def test_security_contract_replaces_error_trace_identifier(security_text: str) -> None:
    """HTTP error envelopes document correlation_id, not the retired trace_id."""
    section_start = security_text.index("### Structured Error Format")
    section_end = security_text.index("\n## ", section_start)
    error_format = security_text[section_start:section_end]
    assert "trace_id" not in error_format
    assert "correlation_id" in error_format


def test_security_contract_matches_cors_headers(security_text: str) -> None:
    """The CORS table must expose every configured request header."""
    cors_section = security_text[security_text.index("## CORS Origin Allowlist") :]
    for header in (*CORS_REQUEST_HEADERS, CORRELATION_ID_HEADER):
        assert header in cors_section

    expose_row = next(
        (line for line in cors_section.splitlines() if "`expose_headers`" in line),
        "",
    )
    assert expose_row
    assert CORRELATION_ID_HEADER in expose_row
