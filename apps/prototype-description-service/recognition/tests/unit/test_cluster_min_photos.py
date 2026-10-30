"""Unknown counts remain explicit for producers that do not compute them."""

import uuid

import pytest
from pydantic import ValidationError

from recognition.domain.cluster import IdentityCluster
from recognition.interface_adapters.http.schemas.responses import ClusterResponse


def test_legacy_domain_and_response_keep_unknown_count():
    cluster = IdentityCluster(str(uuid.uuid4()), False, 8, id=str(uuid.uuid4()), representatives=[])
    response = ClusterResponse.model_validate(cluster)
    assert cluster.photo_count is None
    assert response.model_dump()["photo_count"] is None


@pytest.mark.parametrize("invalid", [-1, 1.5, True])
def test_response_rejects_invalid_photo_count(invalid):
    with pytest.raises(ValidationError, match="photo_count"):
        ClusterResponse(
            id=str(uuid.uuid4()),
            tenant_id=str(uuid.uuid4()),
            label=None,
            is_labeled=False,
            is_auto_label=False,
            identity_count=8,
            photo_count=invalid,
        )
