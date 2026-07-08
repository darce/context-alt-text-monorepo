"""WBUX-4 INT-01a: per-item drafts read route.

A completed bulk run's generated drafts must be reachable by the operator.
This exercises the GET /scene/describe/run/{id}/items endpoint end to end.
"""

from __future__ import annotations

import asyncio
import uuid

import scene.interface_adapters.http.routers.describe_run as describe_run_mod
from scene.application.describe_run_repository import DescribeRunRepository
from scene.tests.test_describe_run_worker import TENANT_ID, _client, _submit


def _no_worker(monkeypatch):
    async def _noop(**_):
        return None

    monkeypatch.setattr(describe_run_mod, "run_describe_job", _noop)


def test_items_route_returns_persisted_drafts(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, sf):
        run_id = _submit(client, [70, 71]).json()["run_id"]

        async def seed():
            async with sf() as s:
                repo = DescribeRunRepository(s)
                await repo.record_item_result(
                    tenant_id=TENANT_ID,
                    run_id=uuid.UUID(run_id),
                    media_id=70,
                    alt_text_draft="A dog resting on green grass",
                    caption="a dog on grass",
                    provenance={"adapter": "florence", "model_id": "florence-2"},
                )
                await s.commit()

        asyncio.run(seed())

        resp = client.get(f"/scene/describe/run/{run_id}/items")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["run_id"] == run_id
        items = {i["media_id"]: i for i in body["items"]}
        assert set(items) == {70, 71}
        assert items[70]["alt_text_draft"] == "A dog resting on green grass"
        assert items[70]["caption"] == "a dog on grass"
        assert items[70]["provenance"] == {"adapter": "florence", "model_id": "florence-2"}
        # item 71 never described: draft is null, not fabricated.
        assert items[71]["alt_text_draft"] is None


def test_items_route_404_for_unknown_run(monkeypatch):
    _no_worker(monkeypatch)
    with _client() as (client, _sf):
        missing = uuid.uuid4()
        resp = client.get(f"/scene/describe/run/{missing}/items")
        assert resp.status_code == 404
