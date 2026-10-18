"""Only the request that acquired a reservation may release it on failure."""

import uuid

import pytest

from recognition.domain.portal_contracts import UsageTicket
from recognition.interface_adapters.http.deps.usage_admission import admit_usage


@pytest.mark.asyncio
@pytest.mark.parametrize("replay", [True, False], ids=["replay", "fresh"])
async def test_body_exception_releases_only_owned_reservation(replay: bool) -> None:
    requested_job_id = str(uuid.uuid4())
    tenant_id = uuid.uuid4()
    ticket = UsageTicket(
        reservation_id=uuid.uuid4(),
        tenant_id=tenant_id,
        idempotency_key="operation",
        cost_units=1,
        job_id=str(uuid.uuid4()) if replay else requested_job_id,
    )

    class Admission:
        def __init__(self):
            self.releases = []

        async def reserve(self, *_args, **_kwargs):
            return ticket

        async def commit(self, _ticket):
            pass

        async def release(self, released):
            self.releases.append(released)

    service = Admission()
    failure = RuntimeError("admitted body failed")
    with pytest.raises(RuntimeError) as caught:
        async with admit_usage(
            service,
            tenant_id=tenant_id,
            idempotency_key="operation",
            job_id=requested_job_id,
            cost_units=1,
        ) as admitted:
            assert admitted is ticket
            raise failure

    assert caught.value is failure
    assert service.releases == ([] if replay else [ticket])
