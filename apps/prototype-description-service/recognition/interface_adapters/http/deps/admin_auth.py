"""Admin authentication dependency for the recognition ``/admin`` surface.

This gate is deliberately separate from the tenant API-key path
(``deps/auth.py``). It reads a dedicated admin header and compares it against
the shared ``RECOGNITION_ADMIN_TOKEN`` in constant time. It never consults the
tenant ``api_key_header``, the database, or ``AuthContext.is_admin`` — the tenant
auth surface is not an admin authority.

Two equivalent credential paths share the same shared token:

* **Programmatic** — the dedicated admin header (default ``X-Admin-Token``),
  required for every JSON mutation.
* **Browser console** — HTTP Basic auth, because a browser cannot send a custom header.
  The Basic *password* must equal the admin token (the username is ignored). A
  401 carries ``WWW-Authenticate: Basic`` so the browser shows a native prompt.
"""

from __future__ import annotations

import base64
import binascii
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

from recognition.config.security import get_security_settings

_BASIC_CHALLENGE = {"WWW-Authenticate": 'Basic realm="admin"'}


def _matches(value: str, expected: str) -> bool:
    """Constant-time credential compare on UTF-8 bytes; empty inputs never match."""
    return bool(expected) and bool(value) and secrets.compare_digest(value.encode("utf-8"), expected.encode("utf-8"))


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="admin authorization required",
        headers=dict(_BASIC_CHALLENGE),
    )


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
    whose password equals the admin token (browser). Both compare on UTF-8
    *bytes* via ``secrets.compare_digest`` so the comparison does not leak length
    or content via timing AND a non-ASCII credential byte cannot raise
    ``TypeError`` (constant-time string compare rejects non-ASCII). Fails closed:
    missing, empty, mismatched, or non-ASCII credentials raise 401 with a
    ``WWW-Authenticate: Basic`` challenge so a browser re-prompts.
    """
    settings = get_security_settings()
    expected = settings.admin_token

    header_token = request.headers.get(settings.admin_header) or ""
    basic_token = _basic_password(request.headers.get("Authorization")) or ""

    header_ok = _matches(header_token, expected)
    basic_ok = _matches(basic_token, expected)

    if not header_ok and not basic_ok:
        raise _unauthorized()


async def require_admin_header(request: Request) -> None:
    """Require the dedicated admin header for programmatic JSON mutations.

    Basic auth is deliberately NOT accepted here: a browser auto-replays Basic
    credentials, so a cross-site page could otherwise ride the operator's
    session into a JSON mutation. A custom header cannot be attached by a
    cross-site form, which removes that class entirely.

    The 401 deliberately omits ``WWW-Authenticate: Basic``: these routes never
    accept Basic, so challenging would be RFC-misleading and would pop a native
    browser login loop on any cross-site POST that reaches this gate.
    """
    settings = get_security_settings()
    if not _matches(request.headers.get(settings.admin_header) or "", settings.admin_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="admin header authorization required",
        )


def _host_of(value: str | None) -> str | None:
    """Return the lowercased netloc (host[:port]) of a URL/Origin, or None.

    ``Origin`` is a full origin (``scheme://host[:port]``) so ``urlsplit`` yields
    the netloc directly. A bare host (as the ``Host`` header carries) has no
    scheme, so it is returned as-is. Empty/missing input yields ``None``.
    """
    if not value:
        return None
    split = urlsplit(value)
    netloc = split.netloc or split.path  # bare host lands in path when no scheme
    return netloc.lower() or None


async def require_same_origin(request: Request) -> None:
    """Reject cross-origin admin form POSTs (CSRF guard for the browser path).

    The ``POST /admin/ui/*`` form routes are reachable via the browser Basic-auth
    path, which auto-replays credentials — so a cross-site form submission would
    otherwise ride the operator's session. This guard compares the request
    ``Origin`` host against the ``Host`` header; on mismatch it raises 403. When
    ``Origin`` is absent it falls back to the ``Referer`` host. When BOTH are
    absent it allows the request: programmatic header-token clients send neither
    and the header path is not CSRF-exposed (a custom header cannot be set by a
    cross-site form).
    """
    host = _host_of(request.headers.get("Host"))
    origin = _host_of(request.headers.get("Origin"))
    source = origin
    if source is None:
        source = _host_of(request.headers.get("Referer"))
    if source is None:
        return
    if host is None or source != host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cross-origin admin request rejected",
        )


__all__ = ["require_admin", "require_admin_header", "require_same_origin"]
