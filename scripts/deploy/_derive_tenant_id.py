#!/usr/bin/env python3
"""Derive the per-site tenant UUID from a WordPress site URL.

This is the Python mirror of ``TenantIdentity::derive_from_site_url()`` at
``apps/prototype-wp-alt-context/src/api/class-tenant-identity.php``. The
recognition-service reset path (``scripts/deploy/recognition-service.sh``)
must produce the same UUID the plugin sends as ``X-Tenant-ID`` on every
authenticated recognition request, otherwise the bootstrap key is bound to
a tenant the plugin will never request and the backend rejects with
HTTP 403 ``tenant mismatch`` (E15-12-BR-06).

Usage:
    python3 _derive_tenant_id.py <site_url>

Prints the v5-style UUID to stdout. Exits non-zero on missing/empty input.

Lives next to ``recognition-service.sh`` rather than under
``apps/prototype-description-service/`` so the deploy script can call it
without dragging the api package's Python environment into the operator
shell.
"""

from __future__ import annotations

import hashlib
import sys


def derive_tenant_id_from_site_url(site_url: str) -> str:
    normalized = site_url.lower().rstrip("/")
    h = hashlib.sha1(f"acx-site-tenant:{normalized}".encode()).hexdigest()
    time_hi = (int(h[12:16], 16) & 0x0FFF) | 0x5000
    clock_seq = (int(h[16:20], 16) & 0x3FFF) | 0x8000
    return f"{h[0:8]}-{h[8:12]}-{time_hi:04x}-{clock_seq:04x}-{h[20:32]}"


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].strip():
        print("usage: _derive_tenant_id.py <site_url>", file=sys.stderr)
        return 2
    print(derive_tenant_id_from_site_url(argv[1].strip()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
