"""Per-IP sliding-window rate limit for unauthenticated public surfaces (DS-5).

``enforce_rate_limit`` keys off ``AuthContext.api_key_id`` and cannot protect
``GET /x/{slug}`` (no API key). This module keys off the client IP.

Behind a reverse proxy (Caddy TLS termination) ``request.client.host`` is the
proxy socket IP — identical for every external client — so all demo traffic
would share one bucket (global DoS footgun). Set
``RECOGNITION_DEMO_TRUSTED_PROXY_HOPS`` to the number of trusted proxies in
front of the app (Caddy alone → ``1``); the real client is then the entry that
many hops from the RIGHT of ``X-Forwarded-For`` (each proxy appends the peer it
saw). The left-most XFF entries are client-supplied and spoofable, so they are
never trusted. Default ``0`` uses ``request.client.host`` (no-proxy dev/test).
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


def _trusted_proxy_hops() -> int:
    raw = os.getenv("RECOGNITION_DEMO_TRUSTED_PROXY_HOPS", "0")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _client_ip(request: Request) -> str:
    """Resolve the rate-limit key IP, spoof-resistant behind N trusted proxies.

    With ``hops`` trusted proxies, the real client is ``parts[-hops]`` (right of
    what each proxy appended). Left-most XFF entries are attacker-controlled and
    never trusted. ``hops == 0`` → the direct socket peer.
    """
    hops = _trusted_proxy_hops()
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if len(parts) >= hops:
                return parts[-hops]
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
