"""Admin authentication dependency for the recognition ``/admin`` surface.

This gate is deliberately separate from the tenant API-key path
(``deps/auth.py``). It reads a dedicated admin header and compares it against
the shared ``RECOGNITION_ADMIN_TOKEN`` in constant time. It never consults the
tenant ``api_key_header``, the database, or ``AuthContext.is_admin`` — the tenant
auth surface is not an admin authority.

Two equivalent credential paths share the same shared token:

* **Programmatic** — the dedicated admin header (default ``X-Admin-Token``).
* **Browser** — HTTP Basic auth, because a browser cannot send a custom header.
  The Basic *password* must equal the admin token (the username is ignored). A
  401 carries ``WWW-Authenticate: Basic`` so the browser shows a native prompt.
"""

from __future__ import annotations

import base64
import binascii
import secrets

from fastapi import HTTPException, Request, status

from recognition.config.security import get_security_settings

_BASIC_CHALLENGE = {"WWW-Authenticate": 'Basic realm="admin"'}


def _basic_password(authorization: str | None) -> str | None:
    """Return the password from an ``Authorization: Basic ...`` header, or None.

    Tolerant of malformed input: anything that is not a well-formed Basic
    credential yields ``None`` so the caller falls through to a 401.
    """
    if not authorization:
        return None
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    _, sep, password = decoded.partition(":")
    if not sep:
        return None
    return password


async def require_admin(request: Request) -> None:
    """Reject requests lacking a valid shared admin token.

    Accepts EITHER the dedicated admin header (programmatic) OR HTTP Basic auth
    whose password equals the admin token (browser). Both compare with
    ``secrets.compare_digest`` so the comparison does not leak length or content
    via timing. Fails closed: missing, empty, or mismatched credentials raise
    401 with a ``WWW-Authenticate: Basic`` challenge so a browser re-prompts.
    """
    settings = get_security_settings()
    expected = settings.admin_token

    header_token = request.headers.get(settings.admin_header) or ""
    basic_token = _basic_password(request.headers.get("Authorization")) or ""

    header_ok = bool(expected) and bool(header_token) and secrets.compare_digest(header_token, expected)
    basic_ok = bool(expected) and bool(basic_token) and secrets.compare_digest(basic_token, expected)

    if not header_ok and not basic_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin authorization required",
            headers=dict(_BASIC_CHALLENGE),
        )


__all__ = ["require_admin"]
