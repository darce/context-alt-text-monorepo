"""Per-IP sliding-window rate limit for unauthenticated public surfaces (DS-5).

``enforce_rate_limit`` keys off ``AuthContext.api_key_id`` and cannot protect
``GET /x/{slug}`` (no API key). This module keys off ``request.client.host``.

Default client identity is ``request.client.host``. TLS termination at Caddy
may set ``X-Forwarded-For``; only honour it when
``RECOGNITION_DEMO_TRUST_X_FORWARDED_FOR=1`` so clients cannot spoof the key
behind a direct connection.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque

from fastapi import HTTPException, Request, status

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


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _client_ip(request: Request) -> str:
    if _bool_env("RECOGNITION_DEMO_TRUST_X_FORWARDED_FOR", False):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Left-most is the original client when trusted proxy prepends.
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def demo_resolve_rpm() -> int:
    raw = os.getenv("RECOGNITION_DEMO_RESOLVE_RPM", "30")
    try:
        return max(0, int(raw))
    except ValueError:
        return 30


async def enforce_ip_rate_limit(request: Request) -> None:
    """Apply a sliding-window per-IP rate limit for public demo resolve."""
    limit = demo_resolve_rpm()
    if limit <= 0:
        return

    key = _client_ip(request)
    now = time.monotonic()

    async with _state_lock:
        window = _state.setdefault(key, deque())
        _prune(window, now)
        if len(window) >= limit:
            oldest = window[0]
            retry_after = max(0, int(oldest + _WINDOW_SECONDS - now) + 1)
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


__all__ = ["demo_resolve_rpm", "enforce_ip_rate_limit"]
