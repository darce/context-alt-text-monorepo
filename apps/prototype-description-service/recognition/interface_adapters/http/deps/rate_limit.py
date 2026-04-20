"""Per-api-key sliding-window rate limit dependency.

Runs after ``require_auth`` via a FastAPI dependency chain, so the resolved
``AuthContext`` (including ``api_key_id`` and ``rate_limit_tier``) drives
the counter. Single-process, in-memory — correct only under single-worker
deployments (enforced by deployment contract).

On breach: raises ``HTTPException(429, "rate limit exceeded")`` with
``Retry-After`` and ``X-RateLimit-*`` response headers, matching the
auth-boundary 401/403 shape.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import Depends, HTTPException, status

from recognition.config.security import RateLimitTier, get_security_settings, tier_rpm
from recognition.interface_adapters.http.deps.auth import AuthContext, require_auth
from recognition.observability.auth_audit import emit_auth_event

_WINDOW_SECONDS = 60

_state: dict[str, deque[float]] = {}
_state_lock = asyncio.Lock()


def _reset_state_for_tests() -> None:
    """Testing seam: clear the counter dict between tests."""
    _state.clear()


def _prune(window: deque[float], now: float) -> None:
    cutoff = now - _WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.popleft()


async def enforce_rate_limit(auth: AuthContext = Depends(require_auth)) -> AuthContext:
    """Apply a sliding-window per-key rate limit.

    Bypass when auth is disabled, or when the caller is a dev key
    (``api_key_id is None and is_admin``).
    """
    if not auth.enabled:
        return auth
    if auth.api_key_id is None and auth.is_admin:
        return auth

    settings = get_security_settings()
    limit = tier_rpm(auth.rate_limit_tier, settings)
    if limit <= 0:
        return auth

    key = auth.api_key_id or "__anon__"
    now = time.monotonic()

    async with _state_lock:
        window = _state.setdefault(key, deque())
        _prune(window, now)
        if len(window) >= limit:
            oldest = window[0]
            retry_after = max(0, int(oldest + _WINDOW_SECONDS - now) + 1)
            emit_auth_event(
                "rate_limit",
                api_key_id=auth.api_key_id,
                key_hash=None,
                tenant_claim=auth.tenant_claim,
                trace_id=None,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate limit exceeded",
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        window.append(now)

    return auth


__all__ = ["enforce_rate_limit", "RateLimitTier"]
