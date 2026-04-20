"""Structured audit-log emitter for authentication/authorization decisions.

Called by `require_auth` on every terminal path (success, invalid key,
expired, revoked, tenant mismatch) and by `enforce_rate_limit` on 429.

Never receives the raw API key — only the stored hash, whose first 12
characters serve as a non-reversible fingerprint for correlation.
"""

from __future__ import annotations

import logging
from typing import Literal

AuthOutcome = Literal[
    "success",
    "invalid_key",
    "expired",
    "revoked",
    "tenant_mismatch",
    "rate_limit",
]

_LOGGER_NAME = "recognition.auth_audit"
_logger = logging.getLogger(_LOGGER_NAME)


def _fingerprint(key_hash: str | None) -> str | None:
    if not key_hash:
        return None
    return key_hash[:12]


def emit_auth_event(
    outcome: AuthOutcome,
    *,
    api_key_id: str | None,
    key_hash: str | None,
    tenant_claim: str | None,
    trace_id: str | None,
) -> None:
    """Emit a structured auth audit record. Raw keys never enter this function."""
    extra = {
        "outcome": outcome,
        "api_key_id": api_key_id,
        "fingerprint": _fingerprint(key_hash),
        "tenant_claim": tenant_claim,
        "trace_id": trace_id,
    }
    _logger.info("auth_event outcome=%s", outcome, extra=extra)


__all__ = ["emit_auth_event", "AuthOutcome"]
