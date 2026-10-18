"""Hand-written HTML console for the operator ``/admin`` surface.

Renders a full HTML document with f-strings and escapes **every** dynamic value
via :func:`html.escape`. There is intentionally no template engine, no partial-
swap script library, and no static-asset mount: those are not project
dependencies and a tailnet-gated single-operator surface has no delivery path for
them. Plain HTML ``<form>`` elements POST and the handlers 303-redirect back to
``/admin/``.

The raw minted key is surfaced exactly once (when ``minted_key`` is set) and is
never re-rendered; ``api_key_hash`` is never rendered at all.
"""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol

from recognition.config.security import RateLimitTier


class _TenantView(Protocol):
    id: object
    site_url: object
    created_at: datetime | None


class _KeyView(Protocol):
    id: object
    rate_limit_tier: object
    created_at: datetime | None
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


def _esc(value: object) -> str:
    """HTML-escape any value's string form (None → empty string)."""
    if value is None:
        return ""
    return html.escape(str(value))


def _fmt_ts(value: datetime | None) -> str:
    """Escaped ISO timestamp, or '—' when absent."""
    if value is None:
        return "&mdash;"
    return html.escape(value.isoformat())


def _key_status(key: _KeyView) -> str:
    """Derive a display status from the stored timestamps (escaped)."""
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None:
        expires = key.expires_at
        now = datetime.now(tz=expires.tzinfo) if expires.tzinfo is not None else datetime.now()  # noqa: DTZ005
        if expires <= now:
            return "expired"
    return "active"


def _tier_options() -> str:
    return "".join(f'<option value="{_esc(tier.value)}">{_esc(tier.value)}</option>' for tier in RateLimitTier)


def _key_row(key: _KeyView) -> str:
    revoke_btn = ""
    if key.revoked_at is None:
        revoke_btn = (
            f'<form method="post" action="/admin/ui/keys/{_esc(key.id)}/revoke" '
            f'style="margin:0">'
            f'<button type="submit">Revoke</button></form>'
        )
    return (
        "<tr>"
        f"<td><code>{_esc(key.id)}</code></td>"
        f"<td>{_esc(_key_status(key))}</td>"
        f"<td>{_esc(key.rate_limit_tier)}</td>"
        f"<td>{_fmt_ts(key.created_at)}</td>"
        f"<td>{_fmt_ts(key.last_used_at)}</td>"
        f"<td>{_fmt_ts(key.expires_at)}</td>"
        f"<td>{_fmt_ts(key.revoked_at)}</td>"
        f"<td>{revoke_btn}</td>"
        "</tr>"
    )


def _keys_table(keys: Sequence[_KeyView]) -> str:
    if not keys:
        return "<p><em>No keys.</em></p>"
    rows = "".join(_key_row(key) for key in keys)
    return (
        '<table border="1" cellpadding="4" cellspacing="0">'
        "<thead><tr>"
        "<th>Key ID</th><th>Status</th><th>Tier</th><th>Created</th>"
        "<th>Last used</th><th>Expires</th><th>Revoked</th><th></th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _truncation_note(shown: int, total: int) -> str:
    """Escaped 'showing N of M keys' banner when the per-tenant cap truncated keys."""
    if total <= shown:
        return ""
    return f'<p class="truncated"><em>Showing {_esc(shown)} of {_esc(total)} keys.</em></p>'


def _tenant_section(tenant: _TenantView, keys: Sequence[_KeyView], total_keys: int | None = None) -> str:
    shown = len(keys)
    total = total_keys if total_keys is not None else shown
    return (
        '<section class="tenant">'
        f"<h3>{_esc(tenant.site_url)}</h3>"
        f"<p>Tenant ID: <code>{_esc(tenant.id)}</code> &middot; "
        f"Created: {_fmt_ts(tenant.created_at)}</p>"
        f"{_truncation_note(shown, total)}"
        f"{_keys_table(keys)}"
        f'<form method="post" action="/admin/ui/keys">'
        f'<input type="hidden" name="tenant_id" value="{_esc(tenant.id)}">'
        '<label>Tier <select name="tier">'
        f"{_tier_options()}"
        "</select></label> "
        '<label>Expires in days <input type="number" name="expires_in_days" min="1" placeholder="never"></label> '
        '<button type="submit">Mint key</button>'
        "</form>"
        "</section>"
    )


def _minted_block(minted_key: str) -> str:
    return (
        '<div class="minted" style="border:2px solid #b8860b;padding:1em;background:#fffbe6">'
        "<strong>New API key (shown once):</strong>"
        f"<pre><code>{_esc(minted_key)}</code></pre>"
        "<p>Copy it now &mdash; it will not be shown again.</p>"
        "</div>"
    )


def render_console(
    *,
    tenants: Sequence[_TenantView],
    keys_by_tenant: Mapping[object, Sequence[_KeyView]],
    totals_by_tenant: Mapping[object, int] | None = None,
    minted_key: str | None = None,
    message: str | None = None,
) -> str:
    """Return the full escaped HTML document for the admin console.

    Args:
        tenants: tenant rows in display order.
        keys_by_tenant: maps a tenant id to that tenant's (possibly capped) keys.
        totals_by_tenant: maps a tenant id to its PRE-cap key count; when a tenant's
            rendered key list is shorter than its total, a "showing N of M" note is
            rendered. Defaults to the rendered count (no truncation note) when None.
        minted_key: when set, the raw key is rendered once in a highlighted box.
        message: an optional escaped status banner.
    """
    banner = f'<p class="message">{_esc(message)}</p>' if message else ""
    minted = _minted_block(minted_key) if minted_key else ""

    if tenants:
        tenant_sections = "".join(
            _tenant_section(
                t,
                keys_by_tenant.get(t.id, ()),
                totals_by_tenant.get(t.id) if totals_by_tenant is not None else None,
            )
            for t in tenants
        )
    else:
        tenant_sections = "<p><em>No tenants yet.</em></p>"

    create_tenant_form = (
        '<section class="create-tenant">'
        "<h2>Create tenant</h2>"
        '<form method="post" action="/admin/ui/tenants">'
        '<label>Tenant ID <input type="text" name="tenant_id" required '
        'placeholder="UUID"></label> '
        '<label>Site URL <input type="url" name="site_url" required '
        'placeholder="https://example.com"></label> '
        '<button type="submit">Create / update tenant</button>'
        "</form>"
        "</section>"
    )

    return (
        "<!DOCTYPE html>"
        '<html lang="en"><head><meta charset="utf-8">'
        "<title>Admin console</title></head>"
        "<body>"
        "<h1>Tenant &amp; API-key admin</h1>"
        f"{banner}"
        f"{minted}"
        f"{create_tenant_form}"
        '<section class="tenants"><h2>Tenants</h2>'
        f"{tenant_sections}"
        "</section>"
        "</body></html>"
    )


__all__ = ["render_console"]
