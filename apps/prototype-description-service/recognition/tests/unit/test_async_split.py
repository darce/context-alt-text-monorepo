"""Tests for async split request validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recognition.interface_adapters.http.schemas.requests import SplitClusterRequest


def test_split_request_validates_mode() -> None:
    """Async mode must be either 'sync' or 'async'."""
    valid = SplitClusterRequest(
        tenant_id="tenant-123",
        mode="async",
    )
    assert valid.mode == "async"

    with pytest.raises(ValidationError):
        SplitClusterRequest(tenant_id="tenant-123", mode="invalid")
