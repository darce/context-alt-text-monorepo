"""Shared per-mutation dependency for the cluster concern routers.

Extracted from the former ``clusters.py`` god-router (Slice 6). The tenant-match
guard was inlined ~12× across admission, snapshot, and topology handlers; it is
the one piece of logic those otherwise-disjoint routers share.
"""

from __future__ import annotations

from fastapi import HTTPException, status


def assert_tenant_match(auth, tenant_id: str) -> None:
    """Raise 403 when an authenticated tenant claim targets a different tenant.

    No-op when there is no auth context or no tenant claim (anonymous / service
    callers), preserving the exact behaviour of the inlined guard it replaces.
    """
    if auth and auth.tenant_claim and auth.tenant_claim != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="tenant mismatch")
