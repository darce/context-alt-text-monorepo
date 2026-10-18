"""Unit tests for the shared per-mutation cluster dependency (Slice 6, REVB-1).

`assert_tenant_match` replaced ~14 inlined tenant-claim guards across the cluster
concern routers; centralization makes a single inverted condition a tenant-
isolation hole across every cluster route, so pin all three branches here.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException, status

from recognition.interface_adapters.http.routers.clusters_common import assert_tenant_match


def test_matching_tenant_claim_does_not_raise() -> None:
    assert_tenant_match(SimpleNamespace(tenant_claim="tenant-1"), "tenant-1")


def test_mismatched_tenant_claim_raises_403() -> None:
    with pytest.raises(HTTPException) as exc_info:
        assert_tenant_match(SimpleNamespace(tenant_claim="tenant-1"), "tenant-2")
    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "tenant mismatch"


def test_no_auth_does_not_raise() -> None:
    assert_tenant_match(None, "tenant-1")


def test_empty_tenant_claim_does_not_raise() -> None:
    # Anonymous / service callers carry no tenant claim; the guard must be a no-op.
    assert_tenant_match(SimpleNamespace(tenant_claim=None), "tenant-1")
    assert_tenant_match(SimpleNamespace(tenant_claim=""), "tenant-1")
