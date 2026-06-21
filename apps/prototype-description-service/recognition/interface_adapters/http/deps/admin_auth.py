"""Admin authentication dependency for the recognition ``/admin`` surface.

This gate is deliberately separate from the tenant API-key path
(``deps/auth.py``). It reads a dedicated admin header and compares it against
the shared ``RECOGNITION_ADMIN_TOKEN`` in constant time. It never consults the
tenant ``api_key_header``, the database, or ``AuthContext.is_admin`` — the tenant
auth surface is not an admin authority.
"""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status

from recognition.config.security import get_security_settings


async def require_admin(request: Request) -> None:
    """Reject requests lacking a valid shared admin token on the dedicated header.

    Fails closed: a missing, empty, or mismatched token raises 401. The token is
    read only from ``settings.admin_header`` and compared with
    ``secrets.compare_digest`` so the comparison does not leak length or content
    via timing.
    """
    settings = get_security_settings()
    provided = request.headers.get(settings.admin_header) or ""
    expected = settings.admin_token

    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authorization required",
        )


__all__ = ["require_admin"]
